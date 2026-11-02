"""Safqa ERP - Flet application shell: services, routing, shared helpers."""

import asyncio
import dataclasses
import time
import os
import traceback

import flet as ft

from .. import __version__, config, selftest
from ..ai import DEFAULT_MODEL, ClaudeClient
from ..billing import Subscription
from ..log import log, system_property
from ..storage import Store
from . import ui


def data_dir():
    d = os.environ.get("FLET_APP_STORAGE_DATA") or os.path.join(os.path.expanduser("~"), ".safqa")
    os.makedirs(d, exist_ok=True)
    return d


class App:
    """Shared state and services for every view."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.dir = data_dir()
        self.docs_dir = os.path.join(self.dir, "documents")
        os.makedirs(self.docs_dir, exist_ok=True)
        self.db_path = os.path.join(self.dir, "safqa.db")
        self.store = Store(self.db_path)
        self.sub = Subscription(self.store)
        self.picker = ft.FilePicker()
        self.share = ft.Share()
        self.clipboard = ft.Clipboard()
        self.tab = 0
        self.state = {}
        from ..cloud import Account
        self.account = Account(self.store)
        self.sync_status = {"state": "idle", "error": None}

    # ------------------------------------------------------------ navigation
    def go(self, route):
        self.page.navigate(route)

    def refresh(self):
        build_views(self)

    def remove_document_file(self, path):
        """Delete a stored document file, but only inside the app's documents folder."""
        if not path:
            return
        real = os.path.realpath(path)
        if os.path.dirname(real) != os.path.realpath(self.docs_dir):
            return
        try:
            os.remove(real)
        except OSError:
            pass

    def company(self):
        return self.store.get_json("company", {}) or {}

    # ------------------------------------------------------------ AI
    def ai_client(self):
        model = self.store.get("ai_model", DEFAULT_MODEL)
        acc = self.account
        if acc.connected and acc.org_id and acc.me.get("ai") and not self.store.get("api_key"):
            # AI included in the company's Safqa Cloud subscription.
            return ClaudeClient(model=model, base_url=acc.url + "/ai", token=acc.token, org_id=acc.org_id)
        mode = self.store.get("ai_mode", "proxy" if config.DEFAULT_PROXY_URL else "direct")
        if mode == "proxy":
            return ClaudeClient(model=model, base_url=self.store.get("proxy_url", config.DEFAULT_PROXY_URL),
                                license_key=self.store.get("license_key", ""))
        return ClaudeClient(api_key=self.store.get("api_key", ""), model=model)

    # ------------------------------------------------------------ async helpers
    async def run(self, message, fn, *args):
        """Run blocking fn in a thread with a progress dialog; returns its result
        or None after showing the error."""
        busy = ui.Busy(self.page, message)
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            log("ERROR " + traceback.format_exc())
            busy.close()
            busy = None
            ui.info(self.page, "Erreur", str(exc) or exc.__class__.__name__)
            return None
        finally:
            if busy:
                busy.close()

    # ------------------------------------------------------------ Safqa Cloud sync
    def sync_now(self, manual=False):
        self.task(self._sync, manual)

    async def _sync(self, manual=False):
        from .. import cloud
        acc = self.account
        if self.sync_status.get("state") == "running" or not (acc.connected and acc.org_id):
            return
        self.sync_status = {"state": "running", "error": None}
        if manual:
            self.refresh()
        try:
            res = await asyncio.to_thread(cloud.synchronize, self.store, acc, self.docs_dir)
        except cloud.CloudError as exc:
            self.sync_status = {"state": "idle", "error": str(exc), "at": time.time()}
            if exc.status == 401:                      # session revoked or expired
                acc.forget()
                ui.snack(self.page, "Session expirée : reconnectez-vous (Plus › Compte & équipe).", error=True)
                self.refresh()
            elif manual:
                ui.snack(self.page, str(exc), error=True)
                self.refresh()
            return
        except Exception as exc:  # noqa: BLE001
            log("ERROR sync " + traceback.format_exc())
            self.sync_status = {"state": "idle", "error": "Erreur de synchronisation : %s" % exc, "at": time.time()}
            return
        self.sync_status = {"state": "idle", "error": None, "at": time.time(), "last": res}
        if manual:
            ui.snack(self.page, "Synchronisé : %d envoyé(s), %d reçu(s)" % (res["sent"], res["received"]))
        if res["received"] or manual:
            self.refresh()

    async def sync_loop(self):
        """Background sync: quickly after local changes, otherwise every 2 minutes."""
        last = 0.0
        while True:
            await asyncio.sleep(15)
            try:
                acc = self.account
                if not (acc.connected and acc.org_id):
                    continue
                if self.store.sync_pending() or time.time() - last > 120:
                    last = time.time()
                    await self._sync()
            except Exception:  # noqa: BLE001 - never stop the loop
                log("ERROR sync loop " + traceback.format_exc())

    def task(self, coro_fn, *args):
        self.page.run_task(coro_fn, *args)

    def export(self, data, filename, mime, title="Exporter"):
        """Share sheet (WhatsApp, e-mail…) or save to the device."""
        holder = {}

        async def share(e):
            ui.close(self.page, holder.get("dlg"))
            try:
                await self.share.share_files([ft.ShareFile.from_bytes(data, mime_type=mime, name=filename)],
                                             subject=filename)
            except Exception as exc:  # noqa: BLE001
                log("ERROR share " + traceback.format_exc())
                ui.info(self.page, "Partage impossible", str(exc))

        async def save(e):
            ui.close(self.page, holder.get("dlg"))
            try:
                # No extension filter: Android's picker rejects extensions it has no MIME type for.
                path = await self.picker.save_file(dialog_title="Enregistrer %s" % filename, file_name=filename,
                                                   src_bytes=data)
                if path is not None or self.page.web:
                    ui.snack(self.page, "Fichier enregistré : %s" % (os.path.basename(path) if path else filename))
            except Exception as exc:  # noqa: BLE001
                log("ERROR save " + traceback.format_exc())
                ui.info(self.page, "Enregistrement impossible", str(exc))

        size = "%d Ko" % max(1, len(data) // 1024)
        content = ft.Column([
            ui.list_row(filename, size, icon=ft.Icons.PICTURE_AS_PDF if mime == "application/pdf" else ft.Icons.DESCRIPTION),
            ui.primary_btn("Partager (WhatsApp, e-mail…)", share, ft.Icons.SHARE, expand=True),
            ui.outline_btn("Enregistrer sur l'appareil", save, ft.Icons.DOWNLOAD, expand=True),
        ], tight=True, spacing=10)
        holder["dlg"] = ui.info(self.page, title, content)

    async def pick_file(self, extensions):
        """Returns (name, bytes) of a chosen file, or (None, None)."""
        try:
            files = await self.picker.pick_files(dialog_title="Choisir un fichier",
                                                 file_type=ft.FilePickerFileType.CUSTOM,
                                                 allowed_extensions=extensions, with_data=True)
        except Exception:  # noqa: BLE001 - some Android pickers reject custom extensions
            log("WARN pick_files custom filter failed, retrying without filter")
            files = await self.picker.pick_files(dialog_title="Choisir un fichier", with_data=True)
        if not files:
            return None, None
        f = files[0]
        ext = (f.name or "").rsplit(".", 1)[-1].lower()
        if extensions and ext not in [x.lower() for x in extensions]:
            ui.info(self.page, "Format non pris en charge",
                    "Choisissez un fichier %s." % ", ".join("." + x for x in extensions))
            return None, None
        data = f.bytes
        if data is None and f.path and os.path.exists(f.path):
            with open(f.path, "rb") as fh:
                data = fh.read()
        if not data:
            ui.info(self.page, "Fichier illisible", "Le fichier choisi est vide ou inaccessible.")
            return None, None
        return f.name, data


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

def parse_route(route):
    path, _, query = (route or "/").partition("?")
    params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
    parts = [p for p in path.split("/") if p]
    return parts, params


def build_views(app):
    from .views import more, tenders, workspace
    page = app.page
    parts, params = parse_route(page.route)
    path = page.route
    if app.state.get("built_path") not in (None, path):
        close_stale_dialogs(page)
        app.state.pop("consumed_new", None)
    app.state["built_path"] = path
    views = [root_view(app)]
    try:
        if parts[:1] == ["marche"] and len(parts) >= 2:
            pid = int(parts[1])
            views.append(workspace.view(app, pid, params.get("tab")))
            if len(parts) >= 4 and parts[2] == "doc":
                views.append(workspace.document_view(app, pid, int(parts[3])))
        elif parts[:1] == ["ao"] and len(parts) >= 2:
            views.append(tenders.detail_view(app, int(parts[1])))
        elif parts[:1] == ["tiers"] and len(parts) >= 2:
            views.append(more.tier_view(app, int(parts[1])))
        elif parts[:1] == ["module"] and len(parts) >= 2:
            views.append(more.module_view(app, parts[1], params))
    except Exception:  # noqa: BLE001 - show the error instead of a blank screen
        text = traceback.format_exc()
        log("ERROR view " + text)
        views.append(ft.View(route=page.route, appbar=ft.AppBar(title=ui.txt("Erreur", color="#FFFFFF"),
                                                                bgcolor=ui.PRIMARY),
                             controls=[ui.txt("Une erreur est survenue :", 15, ft.FontWeight.W_600),
                                       ui.txt(text, 11, selectable=True)], scroll=ft.ScrollMode.AUTO))
    # Re-use the View objects already on screen: replacing them makes Flutter
    # rebuild its navigator pages, and any dialog opened from the old page can
    # then no longer be closed (Enregistrer / Annuler appear dead).
    final = []
    for i, v in enumerate(views):
        cur = page.views[i] if i < len(page.views) else None
        if cur is not None and cur.route == v.route:
            adopt(cur, v)
            final.append(cur)
        else:
            final.append(v)
    if [id(v) for v in page.views] != [id(v) for v in final]:
        page.views.clear()
        page.views.extend(final)
    page.update()
    open_requested_form(app, parts, params)


_VIEW_FIELDS = [f.name for f in dataclasses.fields(ft.View)
                if not f.name.startswith("_") and f.name not in ("data", "key")]


def adopt(cur, new):
    """Copy a freshly built view's content into the view already displayed."""
    for name in _VIEW_FIELDS:
        setattr(cur, name, getattr(new, name))


def close_stale_dialogs(page):
    """A dialog left open must not survive a change of screen."""
    holder = getattr(page, "_dialogs", None)
    for dlg in list(getattr(holder, "controls", None) or []):
        if getattr(dlg, "open", False) and not isinstance(dlg, ft.SnackBar):
            ui.close(page, dlg)


def open_requested_form(app, parts, params):
    """Deep links such as /marche/3?tab=journal&new=1 open the matching form once."""
    if params.get("new") != "1" or app.state.get("consumed_new") == app.page.route:
        return
    app.state["consumed_new"] = app.page.route
    if parts[:1] != ["marche"] or len(parts) != 2:
        return
    from .. import erp
    from .views import workspace
    try:
        pid = int(parts[1])
        x = workspace.Ctx(app, pid, erp.project_state(app.store, pid))
        if params.get("tab") == "journal":
            workspace.journal_form(x)
        elif params.get("tab") == "decomptes":
            workspace.new_decompte(x)
    except Exception:  # noqa: BLE001 - never break navigation for a convenience
        log("ERROR open form " + traceback.format_exc())


TABS = [("Accueil", ft.Icons.SPACE_DASHBOARD_OUTLINED, ft.Icons.SPACE_DASHBOARD),
        ("Marchés", ft.Icons.WORK_OUTLINE, ft.Icons.WORK),
        ("Offres", ft.Icons.GAVEL_OUTLINED, ft.Icons.GAVEL),
        ("Finances", ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, ft.Icons.ACCOUNT_BALANCE_WALLET),
        ("Plus", ft.Icons.APPS_OUTLINED, ft.Icons.APPS)]


def root_view(app):
    from .. import erp
    from .views import dashboard, finance, more, projects, tenders
    builders = [dashboard.build, projects.build, tenders.build, finance.build, more.build]
    title, actions, fab, body = builders[app.tab](app)

    def change(e):
        app.tab = e.control.selected_index
        app.refresh()

    async def back_to_home(e):
        # Android back on a secondary tab returns to the dashboard instead of closing the app.
        try:
            await e.control.confirm_pop(False)
        except Exception:  # noqa: BLE001 - no pending confirmation (tests, web)
            pass
        app.tab = 0
        app.refresh()

    st = app.sub.status()
    search = ft.IconButton(ft.Icons.SEARCH, icon_color="#FFFFFF", tooltip="Rechercher",
                           on_click=lambda e: app.go("/module/recherche"))
    ai = ft.IconButton(ft.Icons.AUTO_AWESOME, icon_color="#FFD089", tooltip="Safqa IA",
                       on_click=lambda e: app.go("/module/assistant"))
    sync = cloud_indicator(app)
    appbar = ft.AppBar(title=ft.Column([ui.txt(title, 19, ft.FontWeight.W_700, "#FFFFFF"),
                                        ui.txt((app.company().get("name") or "Safqa ERP") + " · " + st["label"],
                                               11.5, color="#CFE3EA", max_lines=1)], spacing=0, tight=True),
                       bgcolor=ui.PRIMARY, toolbar_height=62, actions=[sync, ai, search] + (actions or []))
    badges = nav_badges(app, erp)

    def badged(ic, b):
        if not b:
            return ic
        return ft.Icon(ic, badge=ft.Badge(label=str(b), bgcolor=ui.DANGER, text_color="#FFFFFF"))

    # Fade in when the tab changes (not on a plain refresh, so saving a form does not flash).
    content = ft.Container(body, expand=True, animate_opacity=ft.Animation(260, ft.AnimationCurve.EASE_OUT))
    if app.state.get("shown_tab") != app.tab:
        app.state["shown_tab"] = app.tab
        content.opacity = 0.0

        async def fade_in():
            await asyncio.sleep(0.03)
            content.opacity = 1.0
            try:
                content.update()
            except Exception:  # noqa: BLE001 - replaced meanwhile
                pass
        try:
            app.task(fade_in)
        except Exception:  # noqa: BLE001 - no event loop (tests)
            content.opacity = 1.0
    common = dict(route="/", appbar=appbar, bgcolor=ui.BG, padding=0, floating_action_button=fab,
                  can_pop=app.tab == 0, on_confirm_pop=back_to_home if app.tab != 0 else None)
    if is_wide(app.page):
        rail = ft.NavigationRail(
            selected_index=app.tab, on_change=change, bgcolor="#FFFFFF", indicator_color=ui.TINT,
            label_type=ft.NavigationRailLabelType.ALL, min_width=88, group_alignment=-0.9,
            leading=ft.Container(ft.Icon(ft.Icons.APARTMENT, color=ui.PRIMARY, size=30), padding=ft.Padding(0, 12, 0, 8)),
            destinations=[ft.NavigationRailDestination(icon=badged(icon, badges.get(i)),
                                                       selected_icon=badged(sicon, badges.get(i)), label=lbl)
                          for i, (lbl, icon, sicon) in enumerate(TABS)])
        return ft.View(controls=[ft.Row([rail, ft.VerticalDivider(width=1, color=ui.BORDER),
                                         ft.Container(content, expand=True)], spacing=0, expand=True)], **common)
    return ft.View(navigation_bar=ft.NavigationBar(
                       selected_index=app.tab, on_change=change, bgcolor="#FFFFFF", indicator_color=ui.TINT,
                       destinations=[ft.NavigationBarDestination(icon=badged(icon, badges.get(i)),
                                                                 selected_icon=badged(sicon, badges.get(i)), label=lbl)
                                     for i, (lbl, icon, sicon) in enumerate(TABS)]),
                   controls=[content], **common)


WIDE = 900


def cloud_indicator(app):
    acc = app.account
    if not acc.connected:
        icon, color, tip = ft.Icons.CLOUD_OFF_OUTLINED, "#9FC3D1", "Safqa Cloud : non connecté"
    elif app.sync_status.get("state") == "running":
        icon, color, tip = ft.Icons.CLOUD_SYNC, "#FFFFFF", "Synchronisation…"
    elif app.sync_status.get("error"):
        icon, color, tip = ft.Icons.CLOUD_OFF, "#FDA29B", app.sync_status["error"]
    elif app.store.sync_pending():
        icon, color, tip = ft.Icons.CLOUD_UPLOAD_OUTLINED, "#FFD089", "Modifications en attente d'envoi"
    else:
        icon, color, tip = ft.Icons.CLOUD_DONE_OUTLINED, "#A6F4C5", "Synchronisé"
    return ft.IconButton(icon, icon_color=color, tooltip=tip, on_click=lambda e: app.go("/module/compte"))


def is_wide(page):
    try:
        return (page.width or 0) >= WIDE
    except Exception:  # noqa: BLE001 - not known yet
        return False


def nav_badges(app, erp):
    """Counts shown on the navigation bar: critical alerts, tenders due within 7 days,
    overdue receivables."""
    from datetime import date
    out = {}
    try:
        crit = 0
        overdue = 0
        today = date.today()
        for p in app.store.projects():
            s = erp.project_state(app.store, p["id"], today)
            crit += sum(1 for f in s["flags"] if f["severity"] == "critique")
            overdue += sum(1 for f in s["flags"] if f["category"] == "Paiement" and f["severity"] == "élevé")
        due = sum(1 for days, _t in erp.tender_pipeline(app.store.all("tenders"), today)["upcoming"] if days <= 7)
        if crit:
            out[0] = crit
        if due:
            out[2] = due
        if overdue:
            out[3] = overdue
    except Exception:  # noqa: BLE001 - badges are informative only
        log("WARN badges " + traceback.format_exc())
    return out


def page_body(controls, padding=14):
    """Standard scrollable page body."""
    return ft.ListView(controls, padding=ft.Padding(padding, padding, padding, 90), spacing=12, expand=True)


def sub_appbar(title, subtitle=None, actions=None):
    t = [ui.txt(title, 17, ft.FontWeight.W_700, "#FFFFFF", max_lines=1)]
    if subtitle:
        t.append(ui.txt(subtitle, 11.5, color="#CFE3EA", max_lines=1))
    return ft.AppBar(title=ft.Column(t, spacing=0, tight=True), bgcolor=ui.PRIMARY, color="#FFFFFF",
                     toolbar_height=62, actions=actions or [])


def main(page: ft.Page):
    page.title = "Safqa ERP"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ui.PRIMARY, use_material3=True)
    page.bgcolor = ui.BG
    try:
        page.locale_configuration = ft.LocaleConfiguration(supported_locales=[ft.Locale("fr", "FR")],
                                                           current_locale=ft.Locale("fr", "FR"))
    except Exception:  # noqa: BLE001 - locale is cosmetic
        pass
    try:
        app = App(page)
    except Exception:  # noqa: BLE001
        text = traceback.format_exc()
        log("ERROR startup " + text)
        page.add(ui.txt("Safqa n'a pas pu démarrer :", 16, ft.FontWeight.W_600), ui.txt(text, 11, selectable=True))
        return
    page.on_route_change = lambda e=None: build_views(app)

    async def view_pop(e):
        if e.view is not None and len(page.views) > 1:
            page.views.remove(e.view)
            await page.push_route(page.views[-1].route)
    page.on_view_pop = view_pop

    def resized(e=None):
        # Rebuild only when crossing the phone / tablet breakpoint.
        wide = is_wide(page)
        if app.state.get("wide") != wide:
            app.state["wide"] = wide
            app.refresh()
    app.state["wide"] = is_wide(page)
    page.on_resize = resized

    if system_property("debug.safqa.selftest") == "1":
        ok, lines = selftest.run(os.path.join(app.dir, "selftest"))
        if app.store.is_empty():
            from .. import demo
            demo.load_demo(app.store)
    build_views(app)
    log("STARTED version %s" % __version__)
    if app.account.connected:
        app.sync_now()
    app.task(app.sync_loop)
