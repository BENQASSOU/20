"""Last-resort error reporting: instead of closing silently, show the
Python traceback on screen and keep a copy in crash.log.

Only depends on core Kivy widgets so it still works when the rest of the
app (theme, screens) fails to load."""

import os
import sys
import traceback
from datetime import datetime

LOG_NAME = "crash.log"


def record(text, data_dir=None):
    """Print to the system log (adb logcat) and append to crash.log."""
    print("SAFQA-CRASH\n" + text, file=sys.stderr, flush=True)
    for d in filter(None, [data_dir, os.environ.get("ANDROID_PRIVATE"), os.getcwd()]):
        try:
            with open(os.path.join(d, LOG_NAME), "a", encoding="utf-8") as fh:
                fh.write("==== %s ====\n%s\n" % (datetime.now().isoformat(timespec="seconds"), text))
            break
        except OSError:
            continue


def crash_view(text):
    from kivy.metrics import dp, sp
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView

    box = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
    title = Label(text="Safqa a rencontré une erreur au démarrage",
                  bold=True, font_size=sp(17), size_hint_y=None, height=dp(40),
                  color=(0.85, 0.18, 0.13, 1))
    hint = Label(text="Faites une capture d'écran de ce message et envoyez-la au support.",
                 font_size=sp(13), size_hint_y=None, height=dp(36), color=(1, 1, 1, 1))
    for lbl in (title, hint):
        lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
    sv = ScrollView()
    body = Label(text=text, font_size=sp(11.5), size_hint_y=None, halign="left", valign="top",
                 color=(0.9, 0.9, 0.9, 1))
    body.bind(width=lambda i, w: setattr(i, "text_size", (w, None)),
              texture_size=lambda i, ts: setattr(i, "height", ts[1]))
    sv.add_widget(body)
    box.add_widget(title)
    box.add_widget(hint)
    box.add_widget(sv)
    return box


def run_crash_app(text):
    from kivy.app import App

    class CrashApp(App):
        title = "Safqa"

        def build(self):
            return crash_view(text)

    CrashApp().run()


def install_runtime_handler(app):
    """Show errors raised later (button callbacks, clock events) in a
    dialog instead of letting Kivy close the app."""
    from kivy.base import ExceptionHandler, ExceptionManager

    class Handler(ExceptionHandler):
        def handle_exception(self, exc):
            text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            record(text, getattr(app, "user_data_dir", None))
            try:
                from kivy.uix.popup import Popup
                Popup(title="Erreur inattendue", content=crash_view(text),
                      size_hint=(0.95, 0.9)).open()
            except Exception:  # noqa: BLE001 - never raise from the handler
                return ExceptionManager.RAISE
            return ExceptionManager.PASS

    ExceptionManager.add_handler(Handler())
