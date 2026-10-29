#!/usr/bin/env bash
# Install the APK on the emulator, run the on-device self-test and report.
set -u
PKG=ma.safqa.erp
APK=$(ls apk/*.apk | head -n1)
mkdir -p smoke

adb wait-for-device
adb shell getprop ro.product.cpu.abilist
adb install -r -g "$APK" || { echo "INSTALL FAILED"; exit 1; }
adb shell setprop debug.safqa.selftest 1
adb logcat -c
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1

status=unknown
for i in $(seq 1 120); do
  sleep 2
  adb logcat -d > smoke/logcat.txt
  if grep -q "SELFTEST FAILED" smoke/logcat.txt; then status=selftest_failed; break; fi
  if grep -q "SAFQA.*STARTED" smoke/logcat.txt && grep -q "SELFTEST PASSED" smoke/logcat.txt; then status=started; break; fi
  if grep -q "SAFQA.*ERROR" smoke/logcat.txt; then status=python_error; break; fi
  if grep -q "Fatal signal\|FATAL EXCEPTION: main" smoke/logcat.txt && grep -q "$PKG" smoke/logcat.txt; then
    status=crash; break
  fi
  if [ "$i" -gt 15 ] && ! adb shell pidof "$PKG" >/dev/null; then status=process_died; break; fi
done
sleep 8
adb logcat -d > smoke/logcat.txt
adb shell screencap -p /sdcard/screen.png && adb pull /sdcard/screen.png smoke/screen.png

echo "================ STATUS: $status ================"
grep -E "SAFQA|Traceback|Error|flutter|python|AndroidRuntime|DEBUG" smoke/logcat.txt | grep -v "GAv4\|CorpusConfig\|tls" | tail -n 200
[ "$status" = started ]
