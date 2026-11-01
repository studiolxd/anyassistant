#!/bin/sh
# Builds the iPhone and iPad app, installs it on the iPhone or iPad connected by cable (or the one
# whose name or id is given: apps/apple/run.sh "iPad de…") and opens it. Developer Mode on it.
# apps/apple/run.sh mac: the Mac client («AnyAssistant Client», the same app for the Mac), here.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
WANTED="$1"
if [ "$WANTED" = mac ]; then
  xcodegen generate --quiet
  xcodebuild -project AnyAssistant.xcodeproj -scheme AnyAssistant -destination 'platform=macOS,variant=Mac Catalyst' \
    -derivedDataPath build -allowProvisioningUpdates -allowProvisioningDeviceRegistration -quiet build
  APP="build/Build/Products/Debug-maccatalyst/AnyAssistant Client.app"
  pkill -f "AnyAssistant Client.app/Contents/MacOS" 2>/dev/null || true
  open "$APP"
  echo "Open: $HERE/$APP"
  exit 0
fi
# The one by cable first (even locked); one over Wi-Fi if not.
LIST=$(mktemp)
xcrun devicectl list devices --json-output "$LIST" >/dev/null 2>&1 || true
DEVICE=$(python3 - "$LIST" "$WANTED" <<'PY'
import json, sys
devices = json.load(open(sys.argv[1])).get("result", {}).get("devices", [])
wanted = sys.argv[2]
found = []
for d in devices:
    hardware, props, conn = d.get("hardwareProperties", {}), d.get("deviceProperties", {}), d.get("connectionProperties", {})
    udid, name = hardware.get("udid"), props.get("name", "")
    if not udid or hardware.get("platform") != "iOS" or conn.get("pairingState") != "paired":
        continue
    if wanted and wanted not in (udid, name) and wanted not in name:
        continue
    found.append((conn.get("transportType") != "wired", udid))
print(sorted(found)[0][1] if found else "")
PY
)
rm -f "$LIST"
[ -n "$DEVICE" ] || { echo "No iPhone or iPad connected (and trusted)."; exit 1; }
xcodegen generate --quiet
xcodebuild -project AnyAssistant.xcodeproj -scheme AnyAssistant -destination "id=$DEVICE" \
  -derivedDataPath build -allowProvisioningUpdates -allowProvisioningDeviceRegistration -quiet build
xcrun devicectl device install app --device "$DEVICE" build/Build/Products/Debug-iphoneos/AnyAssistant.app >/dev/null
xcrun devicectl device process launch --device "$DEVICE" com.anyassistant >/dev/null
echo "Open on $DEVICE."
