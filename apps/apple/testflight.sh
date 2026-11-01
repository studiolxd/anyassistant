#!/bin/sh
# Uploads the apps to TestFlight (App Store Connect, with the account signed in to Xcode):
# The iPhone and iPad app with the watch app inside (App Store Connect: bundle ID com.anyassistant).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
OUT="$(mktemp -d)"
xcodegen generate --quiet
xcodebuild archive -project AnyAssistant.xcodeproj -scheme AnyAssistant \
  -destination 'generic/platform=iOS' -archivePath "$OUT/AnyAssistant.xcarchive" \
  -allowProvisioningUpdates -quiet
xcodebuild -exportArchive -archivePath "$OUT/AnyAssistant.xcarchive" \
  -exportOptionsPlist ExportOptions.plist -exportPath "$OUT/export" -allowProvisioningUpdates -quiet
rm -rf "$OUT"
echo "Uploaded. In 10-20 minutes it is in TestFlight (on the iPhone), to install on the watch."
