"""Kivy application: wiring of services and screens."""

import os
import threading
import traceback

print("SAFQA-STEP kivy.app", flush=True)
from kivy.app import App
from kivy.clock import Clock
print("SAFQA-STEP kivy window", flush=True)
from kivy.core.window import Window
print("SAFQA-STEP kivy window ready", flush=True)
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import NoTransition, ScreenManager, SlideTransition
from kivy.utils import platform

from . import analysis, config, crash, risk
from .ai import DEFAULT_MODEL, ClaudeClient
from .billing import Subscription
from .platform_android import FilePicker
from .storage import Store
from .ui import widgets as W

print("SAFQA-STEP loading theme", flush=True)
Builder.load_file(os.path.join(os.path.dirname(__file__), "ui", "theme.kv"))

from .ui.screens import AccountScreen, ChatScreen, HomeScreen  # noqa: E402
from .ui.project import DocumentScreen, ProjectFormScreen, ProjectScreen  # noqa: E402


class SafqaApp(App):
    title = "Safqa"

    def build(self):
        crash.install_runtime_handler(self)
        try:
            return self._build()
        except Exception:  # noqa: BLE001 - show the error instead of closing
            self._failed = traceback.format_exc()
            crash.record(self._failed, self.user_data_dir)
            return crash.crash_view(self._failed)

    def _build(self):
        print("SAFQA-STEP build", flush=True)
        Window.clearcolor = W.C.bg
        if platform != "android":
            Window.size = (412, 860)
        Window.softinput_mode = "below_target"
        data = self.user_data_dir
        self.store = Store(os.path.join(data, "safqa.db"))
        self.sub = Subscription(self.store)
        self.docs_dir = os.path.join(data, "documents")
        self.export_dir = os.path.join(data, "exports")
        self.picker = FilePicker(self.docs_dir)

        root = BoxLayout(orientation="vertical")
        self.sm = ScreenManager(transition=SlideTransition(duration=0.18))
        for scr in (HomeScreen(name="home"), ProjectScreen(name="project"),
                    ProjectFormScreen(name="project_form"), DocumentScreen(name="document"),
                    ChatScreen(name="chat"), AccountScreen(name="account")):
            self.sm.add_widget(scr)
        self.nav = W.NavBar()
        self.nav.setup([("home", "Marchés"), ("chat", "Assistant IA"), ("account", "Compte")])
        self.nav.bind(on_select=lambda inst, key: self.go(key, root_tab=True))
        root.add_widget(self.sm)
        root.add_widget(self.nav)
        self.nav.current = "home"
        self._history = []
        Window.bind(on_keyboard=self._on_key)
        return root

    def on_start(self):
        if getattr(self, "_failed", None):
            return
        try:
            self.sm.get_screen("home").refresh()
        except Exception:  # noqa: BLE001
            text = traceback.format_exc()
            crash.record(text, self.user_data_dir)
            self.root.clear_widgets()
            self.root.add_widget(crash.crash_view(text))
            return
        print("SAFQA-STARTED", flush=True)

    # ------------------------------------------------------------ navigation
    def go(self, name, root_tab=False, **kw):
        if root_tab:
            self._history = []
            self.sm.transition = NoTransition()
        else:
            self._history.append(self.sm.current)
            self.sm.transition = SlideTransition(direction="left", duration=0.18)
        scr = self.sm.get_screen(name)
        if hasattr(scr, "load"):
            scr.load(**kw)
        self.sm.current = name
        if name in ("home", "chat", "account"):
            self.nav.current = name

    def back(self):
        if not self._history:
            return False
        name = self._history.pop()
        self.sm.transition = SlideTransition(direction="right", duration=0.18)
        scr = self.sm.get_screen(name)
        if hasattr(scr, "refresh"):
            scr.refresh()
        self.sm.current = name
        if name in ("home", "chat", "account"):
            self.nav.current = name
        return True

    def _on_key(self, window, key, *args):
        if key == 27:  # Android back button
            return self.back()
        return False

    # ------------------------------------------------------------ services
    def ai_client(self):
        mode = self.store.get("ai_mode", "proxy" if config.DEFAULT_PROXY_URL else "direct")
        model = self.store.get("ai_model", DEFAULT_MODEL)
        if mode == "proxy":
            return ClaudeClient(model=model,
                                base_url=self.store.get("proxy_url", config.DEFAULT_PROXY_URL),
                                license_key=self.store.get("license_key", ""))
        return ClaudeClient(api_key=self.store.get("api_key", ""), model=model)

    def project_state(self, pid):
        b = self.store.bundle(pid)
        if not b["project"]:
            return None
        terms = analysis.project_terms(b["documents"])
        # manual overrides saved on the project win over extracted values
        for k, v in (b["project"].get("terms") or {}).items():
            terms[k] = v
        p = dict(b["project"], terms=terms)
        flags = risk.evaluate(p, b["documents"], b["checklist"], b["orders"], b["items"],
                              b["decomptes"], b["receptions"])
        b["project_full"] = p
        b["terms"] = terms
        b["flags"] = flags
        return b

    def run_bg(self, fn, on_done, busy_text=None, on_error=None):
        """Run fn(progress) in a thread; progress(text) updates the dialog."""
        busy = W.Busy(busy_text) if busy_text else None
        if busy:
            busy.open()

        def progress(sub):
            if busy:
                Clock.schedule_once(lambda dt: busy.set(sub=sub), 0)

        def work():
            try:
                res = fn(progress)
            except Exception as exc:  # noqa: BLE001 - reported to the user
                traceback.print_exc()
                msg = str(exc) or exc.__class__.__name__

                def fail(dt):
                    if busy:
                        busy.close()
                    if on_error:
                        on_error(msg)
                    else:
                        W.info("Erreur", msg)
                Clock.schedule_once(fail, 0)
                return

            def ok(dt):
                if busy:
                    busy.close()
                on_done(res)
            Clock.schedule_once(ok, 0)

        threading.Thread(target=work, daemon=True).start()


def run():
    SafqaApp().run()
