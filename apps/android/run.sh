#!/bin/sh
# Builds the Android app and installs it on the phone, tablet or emulator adb sees (USB with USB
# debugging on, or «adb pair» / «adb connect» over Wi-Fi), and opens it. Android 8 or later.
# apps/android/run.sh release: an APK to share (app/build/outputs/apk/release, unsigned).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
[ -f local.properties ] || echo "sdk.dir=${ANDROID_HOME:-$HOME/Library/Android/sdk}" > local.properties
if [ "$1" = release ]; then
  ./gradlew assembleRelease -q
  ls app/build/outputs/apk/release/*.apk
  exit 0
fi
./gradlew assembleDebug -q
adb install -r app/build/outputs/apk/debug/app-debug.apk >/dev/null
adb shell am start -n com.anyassistant/.MainActivity >/dev/null
echo "Open on $(adb devices | awk 'NR==2 {print $1}')."
