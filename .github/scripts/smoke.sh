#!/usr/bin/env bash
# Install the APK on the emulator, launch it and report whether Safqa started.
set -u
PKG=ma.safqa.safqa
APK=$(ls apk/*.apk | head -n1)
mkdir -p smoke

adb wait-for-device
adb shell getprop ro.product.cpu.abilist
adb install -r -g "$APK" || { echo "INSTALL FAILED"; exit 1; }
adb logcat -c
adb shell am start -W -n "$PKG/org.kivy.android.PythonActivity"

status=unknown
for i in $(seq 1 90); do
  sleep 2
  adb logcat -d > smoke/logcat.txt
  if grep -q "SAFQA-STARTED" smoke/logcat.txt; then status=started; break; fi
  if grep -q "SAFQA-CRASH" smoke/logcat.txt; then status=error_screen; break; fi
  if [ "$i" -gt 10 ] && ! adb shell pidof "$PKG" >/dev/null; then status=process_died; break; fi
done
sleep 4
adb logcat -d > smoke/logcat.txt
adb shell screencap -p /sdcard/screen.png && adb pull /sdcard/screen.png smoke/screen.png

echo "================ STATUS: $status ================"
grep -E " (python|PythonActivity|SDL|AndroidRuntime|DEBUG|libc|linker)\b|SAFQA|Traceback|Error" smoke/logcat.txt | tail -n 250
[ "$status" = started ]
