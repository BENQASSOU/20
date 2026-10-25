"""Android integration through pyjnius: document picker, saving to the
public Downloads folder and the share sheet.  Desktop fallbacks keep the
app usable (and testable) on a PC."""

import os
import shutil

from kivy.utils import platform

IS_ANDROID = platform == "android"
_REQUEST_PICK = 4207


def _android():
    from jnius import autoclass
    from android import mActivity
    return autoclass, mActivity


class FilePicker:
    """pick(callback) -> callback(local_path or None, display_name)"""

    def __init__(self, dest_dir):
        self.dest_dir = dest_dir
        os.makedirs(dest_dir, exist_ok=True)
        self._callback = None
        if IS_ANDROID:
            from android import activity
            activity.bind(on_activity_result=self._on_result)

    def pick(self, callback):
        self._callback = callback
        if IS_ANDROID:
            autoclass, act = _android()
            Intent = autoclass("android.content.Intent")
            intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("*/*")
            act.startActivityForResult(intent, _REQUEST_PICK)
        else:
            self._desktop_pick()

    # ---------------------------------------------------------- android
    def _on_result(self, request, result, intent):
        if request != _REQUEST_PICK:
            return
        from kivy.clock import Clock
        cb = self._callback
        if result != -1 or intent is None:  # RESULT_OK = -1
            Clock.schedule_once(lambda dt: cb(None, None), 0)
            return
        try:
            path, name = self._copy_uri(intent.getData())
        except Exception as exc:  # noqa: BLE001 - surface any Java error to the user
            msg = "Erreur : %s" % exc
            Clock.schedule_once(lambda dt: cb(None, msg), 0)
            return
        Clock.schedule_once(lambda dt: cb(path, name), 0)

    def _copy_uri(self, uri):
        autoclass, act = _android()
        resolver = act.getContentResolver()
        name = "document"
        cursor = resolver.query(uri, None, None, None, None)
        if cursor is not None:
            try:
                idx = cursor.getColumnIndex("_display_name")
                if idx >= 0 and cursor.moveToFirst():
                    name = cursor.getString(idx) or name
            finally:
                cursor.close()
        safe = "".join(c for c in name if c.isalnum() or c in "._- ").strip() or "document"
        dest = _unique(os.path.join(self.dest_dir, safe))
        stream = resolver.openInputStream(uri)
        FileOutputStream = autoclass("java.io.FileOutputStream")
        out = FileOutputStream(dest)
        try:
            Build = autoclass("android.os.Build$VERSION")
            if Build.SDK_INT >= 29:
                autoclass("android.os.FileUtils").copy(stream, out)
            else:  # pragma: no cover - old devices
                buf = bytearray(65536)
                while True:
                    n = stream.read(buf)
                    if n <= 0:
                        break
                    out.write(buf, 0, n)
        finally:
            out.close()
            stream.close()
        return dest, name

    # ---------------------------------------------------------- desktop
    def _desktop_pick(self):
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        box = BoxLayout(orientation="vertical", spacing=6)
        fc = FileChooserListView(path=os.path.expanduser("~"),
                                 filters=["*.pdf", "*.docx", "*.txt", "*.csv", "*.PDF"])
        box.add_widget(fc)
        row = BoxLayout(size_hint_y=None, height=48, spacing=6)
        popup = Popup(title="Choisir un document", content=box, size_hint=(0.95, 0.95))

        def done(*_):
            popup.dismiss()
            if fc.selection:
                src = fc.selection[0]
                dest = _unique(os.path.join(self.dest_dir, os.path.basename(src)))
                shutil.copy(src, dest)
                self._callback(dest, os.path.basename(src))
            else:
                self._callback(None, None)

        row.add_widget(Button(text="Annuler", on_release=lambda *_: (popup.dismiss(), self._callback(None, None))))
        row.add_widget(Button(text="Ouvrir", on_release=done))
        box.add_widget(row)
        popup.open()


def _unique(path):
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(path):
        path = "%s_%d%s" % (base, i, ext)
        i += 1
    return path


def save_to_downloads(filename, data, mime, fallback_dir):
    """Write bytes to Download/Safqa (MediaStore on Android 10+).

    Returns (location_label, uri_or_path)."""
    if IS_ANDROID:
        autoclass, act = _android()
        Build = autoclass("android.os.Build$VERSION")
        if Build.SDK_INT >= 29:
            ContentValues = autoclass("android.content.ContentValues")
            Downloads = autoclass("android.provider.MediaStore$Downloads")
            values = ContentValues()
            values.put("_display_name", filename)
            values.put("mime_type", mime)
            values.put("relative_path", "Download/Safqa")
            resolver = act.getContentResolver()
            uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
            stream = resolver.openOutputStream(uri)
            try:
                stream.write(data)
            finally:
                stream.close()
            return "Téléchargements/Safqa/" + filename, uri
    os.makedirs(fallback_dir, exist_ok=True)
    path = _unique(os.path.join(fallback_dir, filename))
    with open(path, "wb") as fh:
        fh.write(data)
    return path, path


def share(uri, mime, subject=""):
    """Open the Android share sheet (WhatsApp, Gmail…) for a saved file."""
    if not IS_ANDROID or isinstance(uri, str):
        return False
    autoclass, act = _android()
    Intent = autoclass("android.content.Intent")
    String = autoclass("java.lang.String")
    intent = Intent(Intent.ACTION_SEND)
    intent.setType(mime)
    intent.putExtra(Intent.EXTRA_STREAM, uri)
    intent.putExtra(Intent.EXTRA_SUBJECT, String(subject))
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    chooser = Intent.createChooser(intent, String("Partager"))
    act.startActivity(chooser)
    return True


def open_url(url):
    import webbrowser
    webbrowser.open(url)
