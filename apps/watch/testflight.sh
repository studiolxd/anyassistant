#!/bin/sh
# Uploads the watch app to TestFlight (App Store Connect, with the account signed in to Xcode).
# Once, before: the app in App Store Connect with the bundle ID com.anyassistant.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
OUT="$(mktemp -d)"
xcodegen generate --quiet
xcodebuild archive -project AnyAssistantWatch.xcodeproj -scheme AnyAssistant \
  -destination 'generic/platform=iOS' -archivePath "$OUT/AnyAssistant.xcarchive" \
  -allowProvisioningUpdates -quiet
xcodebuild -exportArchive -archivePath "$OUT/AnyAssistant.xcarchive" \
  -exportOptionsPlist ExportOptions.plist -exportPath "$OUT/export" -allowProvisioningUpdates -quiet
rm -rf "$OUT"
echo "Uploaded. In 10-20 minutes it is in TestFlight (on the iPhone), to install on the watch."
