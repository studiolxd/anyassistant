#!/bin/sh
# The Apple Watch app: makes the Xcode project (xcodegen) and checks it builds. To install it
# on your watch: open apps/watch/AnyAssistantWatch.xcodeproj, choose your watch and Run.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
xcodegen generate --quiet
xcodebuild -project AnyAssistantWatch.xcodeproj -scheme AnyAssistantWatch -destination 'generic/platform=watchOS' \
  -quiet build CODE_SIGNING_ALLOWED=NO
echo "Built. To install: open $HERE/AnyAssistantWatch.xcodeproj, choose the scheme AnyAssistantWatch and your Apple Watch, and Run (or apps/watch/testflight.sh)."
