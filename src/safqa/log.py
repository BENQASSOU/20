"""Logging that reaches `adb logcat` on Android (tag SAFQA) and stdout
elsewhere, so on-device runs can be diagnosed from CI."""

import ctypes
import os
import sys

_liblog = False


def on_android():
    return hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ


def log(msg):
    msg = str(msg)
    print("SAFQA " + msg, flush=True)
    global _liblog
    if not on_android():
        return
    try:
        if _liblog is False:
            _liblog = ctypes.CDLL("liblog.so")
        for chunk in [msg[i:i + 3000] for i in range(0, len(msg), 3000)] or [""]:
            _liblog.__android_log_write(4, b"SAFQA", chunk.encode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - logging must never break the app
        _liblog = None


def system_property(name):
    """Read an Android system property (e.g. one set with `adb shell setprop`)."""
    if not on_android():
        return os.environ.get(name.upper().replace(".", "_"), "")
    try:
        libc = ctypes.CDLL("libc.so")
        buf = ctypes.create_string_buffer(92)
        libc.__system_property_get(name.encode(), buf)
        return buf.value.decode()
    except Exception:  # noqa: BLE001
        return ""
