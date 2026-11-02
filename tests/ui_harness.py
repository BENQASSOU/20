"""Headless exerciser for the Flet interface.

Builds every screen of the app against a fake Page, validates every control
with Flet's own validators, then invokes every event handler (buttons,
chips, tabs, dropdowns, menus...), fills and submits the dialogs they open,
and reports every exception.  No browser or Flutter engine needed.
"""

import asyncio
import dataclasses
import inspect
import os
import shutil
import tempfile
import traceback

import flet as ft
from flet.utils.validation import validate

SKIP_FIELDS = {"parent", "page", "data", "key", "ref"}
CANCEL_LABELS = {"Annuler", "Fermer"}


class FakeService:
    def __init__(self, *a, **kw):
        self.calls = []

    async def pick_files(self, **kw):
        self.calls.append(("pick_files", kw))
        return []

    async def save_file(self, **kw):
        self.calls.append(("save_file", kw))
        return "/tmp/saved"

    async def share_files(self, files, **kw):
        self.calls.append(("share_files", files))

    async def set(self, value):
        self.calls.append(("clipboard", value))


class FakePage:
    def __init__(self):
        object.__setattr__(self, "route", "/")
        self.views = []
        self.dialogs = []
        self.tasks = []
        self.web = False
        self.on_route_change = None
        self.on_view_pop = None

    def update(self, *controls):
        pass

    def add(self, *controls):
        pass

    def navigate(self, route):
        self.route = route
        if self.on_route_change:
            self.on_route_change(None)

    async def push_route(self, route):
        self.navigate(route)

    def show_dialog(self, dialog):
        dialog.open = True
        self.dialogs.append(dialog)

    def pop_dialog(self):
        dlg = next((d for d in reversed(self.dialogs) if d.open), None)
        if dlg is not None:
            dlg.open = False
        return dlg

    def run_task(self, fn, *args):
        self.tasks.append(fn(*args))


class Ev:
    def __init__(self, control, page):
        self.control = control
        self.page = page
        self.data = None
        self.view = None


def children(c):
    for f in dataclasses.fields(c):
        if f.name.startswith("_") or f.name in SKIP_FIELDS:
            continue
        v = getattr(c, f.name, None)
        if isinstance(v, ft.BaseControl):
            yield v
        elif isinstance(v, (list, tuple)):
            for x in v:
                if isinstance(x, ft.BaseControl):
                    yield x


def walk(root):
    seen = set()
    stack = [root]
    while stack:
        c = stack.pop(0)
        if id(c) in seen:
            continue
        seen.add(id(c))
        yield c
        stack[0:0] = list(children(c))


def handlers(root):
    out = []
    for c in walk(root):
        for f in dataclasses.fields(c):
            if f.name.startswith("on_") and callable(getattr(c, f.name, None)):
                out.append((c, f.name, getattr(c, f.name)))
    return out


def describe(c):
    for attr in ("content", "label", "text", "tooltip", "value"):
        v = getattr(c, attr, None)
        if isinstance(v, str) and v:
            return "%s(%s)" % (c.__class__.__name__, v[:40])
        if isinstance(v, ft.Text) and v.value:
            return "%s(%s)" % (c.__class__.__name__, v.value[:40])
    icon = getattr(c, "icon", None)
    if icon is not None:
        return "%s(%s)" % (c.__class__.__name__, getattr(icon, "name", icon))
    return c.__class__.__name__


def prepare(c, name, variant=0):
    """Put a control in a state that makes its handler meaningful."""
    if isinstance(c, ft.Dropdown) and c.options:
        c.value = c.options[min(variant, len(c.options) - 1)].key
    elif isinstance(c, (ft.Tabs, ft.NavigationBar)):
        c.selected_index = variant
    elif isinstance(c, ft.Chip):
        c.selected = True
    elif isinstance(c, (ft.Checkbox, ft.Switch)):
        c.value = not bool(c.value)
    elif isinstance(c, ft.TextField) and name in ("on_change", "on_submit"):
        c.value = c.value or "test"


def call(fn, ev, loop):
    try:
        n = len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        n = 1
    res = fn(ev) if n else fn()
    if inspect.isawaitable(res):
        loop.run_until_complete(res)


def drain(page, loop):
    for _ in range(10):
        if not page.tasks:
            return
        tasks, page.tasks = page.tasks, []
        for t in tasks:
            loop.run_until_complete(t)


def fill_form(dialog):
    for c in walk(dialog):
        if isinstance(c, ft.TextField) and not c.value:
            hint = (c.hint_text or "") + " " + str(c.label or "")
            if "JJ/MM" in hint:
                c.value = "01/11/2026"
            elif c.keyboard_type == ft.KeyboardType.NUMBER:
                c.value = "100"
            elif c.password:
                c.value = ""
            else:
                c.value = "Test"
        elif isinstance(c, ft.Dropdown) and c.value is None and c.options:
            c.value = c.options[-1].key if len(c.options) > 1 else c.options[0].key


def action_buttons(dialog):
    acts = getattr(dialog, "actions", None) or []
    out = []
    for a in acts:
        lbl = a.content if isinstance(a.content, str) else getattr(getattr(a, "content", None), "value", "")
        if callable(getattr(a, "on_click", None)):
            out.append((lbl or "", a))
    return out


class Explorer:
    def __init__(self, template_db, empty=False):
        self.template_db = template_db
        self.empty = empty
        self.failures = []
        self.invocations = 0
        self.screens = 0
        self.loop = asyncio.new_event_loop()

    # ------------------------------------------------------------ setup
    def fresh(self, screen):
        from safqa.gui import app as appmod
        d = tempfile.mkdtemp(prefix="safqa_ui_")
        if self.template_db and not self.empty:
            shutil.copy(self.template_db, os.path.join(d, "safqa.db"))
        os.environ["FLET_APP_STORAGE_DATA"] = d
        page = FakePage()
        app = appmod.App(page)
        page.on_route_change = lambda e=None: appmod.build_views(app)
        route, tab, state = screen
        app.tab = tab
        app.state.update(state)
        page.route = route
        appmod.build_views(app)
        return page, app, d

    def fail(self, where, exc_text):
        self.failures.append("%s\n%s" % (where, exc_text))

    # ------------------------------------------------------------ checks
    def validate_tree(self, root, where):
        for c in walk(root):
            try:
                validate(c)
            except Exception:  # noqa: BLE001 - collected
                self.fail("VALIDATION %s :: %s" % (where, describe(c)), traceback.format_exc(limit=2))

    def exercise_dialogs(self, page, app, where, depth=0, before=0):
        if depth > 3:
            return
        new = page.dialogs[before:]
        for dlg in list(new):
            self.validate_tree(dlg, where + " > dialog")
            if isinstance(dlg, (ft.SnackBar, ft.DatePicker)):
                continue
            fill_form(dlg)
            btns = action_buttons(dlg)
            primary = [b for lbl, b in btns if isinstance(b, ft.FilledButton)]
            if primary:
                n = len(page.dialogs)
                try:
                    call(primary[0].on_click, Ev(primary[0], page), self.loop)
                    drain(page, self.loop)
                except Exception:  # noqa: BLE001
                    self.fail("DIALOG ACTION %s > %s" % (where, describe(primary[0])), traceback.format_exc())
                    continue
                if len(page.dialogs) > n:
                    self.exercise_dialogs(page, app, where + " > " + describe(primary[0]), depth + 1, n)
            # inner handlers (date pickers, switches...)
            for c, name, fn in handlers(dlg):
                if c in [b for _l, b in btns]:
                    continue
                prepare(c, name)
                try:
                    call(fn, Ev(c, page), self.loop)
                    drain(page, self.loop)
                except Exception:  # noqa: BLE001
                    self.fail("DIALOG HANDLER %s > %s.%s" % (where, describe(c), name), traceback.format_exc())

    def explore(self, screen):
        try:
            page, app, d = self.fresh(screen)
        except Exception:  # noqa: BLE001
            self.fail("BUILD %s" % (screen,), traceback.format_exc())
            return
        self.screens += 1
        for v in page.views:
            self.validate_tree(v, str(screen))
        top = page.views[-1]
        hs = handlers(top)
        count = len(hs)
        app.store.close()
        shutil.rmtree(d, ignore_errors=True)
        for i in range(count):
            variants = 1
            c0 = hs[i][0]
            if isinstance(c0, (ft.Tabs, ft.NavigationBar)):
                variants = getattr(c0, "length", None) or len(getattr(c0, "destinations", []) or []) or 1
            for variant in range(variants):
                page, app, d = self.fresh(screen)
                try:
                    c, name, fn = handlers(page.views[-1])[i]
                except IndexError:
                    app.store.close()
                    shutil.rmtree(d, ignore_errors=True)
                    continue
                prepare(c, name, variant)
                where = "%s :: %s.%s" % (screen, describe(c), name)
                self.invocations += 1
                n = len(page.dialogs)
                try:
                    call(fn, Ev(c, page), self.loop)
                    drain(page, self.loop)
                    for v in page.views:
                        self.validate_tree(v, where + " (after)")
                    self.exercise_dialogs(page, app, where, before=n)
                except Exception:  # noqa: BLE001
                    self.fail("HANDLER " + where, traceback.format_exc())
                finally:
                    try:
                        app.store.close()
                    except Exception:  # noqa: BLE001
                        pass
                    shutil.rmtree(d, ignore_errors=True)


def all_screens(store):
    from safqa.gui.views import workspace
    screens = []
    for tab in range(5):
        screens.append(("/", tab, {}))
    for sub in range(4):
        screens.append(("/", 3, {"finance_tab": sub}))
    for f in ("receptionne", "clos", "tous"):
        screens.append(("/", 1, {"projects_filter": f}))
    for f in ("tous", "gagne", "perdu", "veille"):
        screens.append(("/", 2, {"tender_filter": f}))
    for p in store.projects():
        for key in workspace.TAB_KEYS:
            screens.append(("/marche/%s?tab=%s" % (p["id"], key), 1, {}))
        for d in store.documents(p["id"]):
            for k, _ in workspace.DOC_TABS:
                screens.append(("/marche/%s/doc/%s" % (p["id"], d["id"]), 1, {"doc_tab_%s" % d["id"]: k}))
    for t in store.all("tenders"):
        screens.append(("/ao/%s" % t["id"], 2, {}))
    for m in ("echeancier", "tiers", "assistant", "rapports", "parametres", "abonnement", "diagnostic", "garanties",
              "recherche", "courriers"):
        screens.append(("/module/%s" % m, 4, {}))
    for q in ("12/2026", "béton", "caution", "témara"):
        screens.append(("/module/recherche", 4, {"search_query": q}))
    for t in store.tiers():
        screens.append(("/tiers/%s" % t["id"], 4, {}))
    screens.append(("/module/inconnu", 4, {}))
    screens.append(("/", 1, {"projects_filter": "tous", "projects_query": "école"}))
    return screens
