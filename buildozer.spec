[app]
title = Safqa
package.name = safqa
package.domain = ma.safqa
source.dir = .
source.include_exts = py,png,kv,txt
source.exclude_dirs = tests,tools,bin,.buildozer,.github,venv,docs
version.regex = __version__ = ['"](.*)['"]
version.filename = %(source.dir)s/safqa/__init__.py

# Pure-Python dependencies only: everything below has a python-for-android
# recipe or installs as a plain wheel.
requirements = python3,kivy==2.3.1,pyjnius,android,sqlite3,openssl,pypdf==5.9.0,typing_extensions,certifi

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #0B4F6C

android.permissions = INTERNET
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a, x86_64
android.accept_sdk_license = True
android.allow_backup = True
android.release_artifact = apk
android.debug_artifact = apk
# Pin a stable python-for-android release and its NDK: the development
# branch resolves Android-only wheels (e.g. charset-normalizer) that its
# own pip step then refuses to install.
android.ndk = 25b
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 0
