"""Safqa - assistant IA pour les marchés publics marocains (entrypoint)."""

import traceback

from safqa import crash

if __name__ == "__main__":
    try:
        from safqa.app import SafqaApp
    except Exception:  # noqa: BLE001 - show any import error instead of closing
        text = traceback.format_exc()
        crash.record(text)
        crash.run_crash_app(text)
    else:
        SafqaApp().run()
