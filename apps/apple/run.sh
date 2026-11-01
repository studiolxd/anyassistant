#!/bin/sh
# Builds the iPhone and iPad app, installs it on the iPhone or iPad connected by cable (or the one
# whose name or id is given: apps/apple/run.sh "iPad de…") and opens it. Developer Mode on it.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
WANTED="$1"
DEVICE=$(xcrun devicectl list devices 2>/dev/null | awk -v w="$WANTED" '
  /connected|available \(paired\)/ && /iPhone|iPad/ && (w == "" || index($0, w)) {
    for (i = 1; i <= NF; i++) if ($i ~ /^[0-9A-Fa-f-]{20,}$/) { print $i; exit }
  }')
[ -n "$DEVICE" ] || { echo "No iPhone or iPad connected (and trusted)."; exit 1; }
xcodegen generate --quiet
xcodebuild -project AnyAssistant.xcodeproj -scheme AnyAssistant -destination "id=$DEVICE" \
  -derivedDataPath build -allowProvisioningUpdates -allowProvisioningDeviceRegistration -quiet build
xcrun devicectl device install app --device "$DEVICE" build/Build/Products/Debug-iphoneos/AnyAssistant.app >/dev/null
xcrun devicectl device process launch --device "$DEVICE" com.anyassistant >/dev/null
echo "Open on $DEVICE."
