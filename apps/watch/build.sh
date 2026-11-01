#!/bin/sh
# The Apple Watch app: makes the Xcode project (xcodegen) and checks it builds. To install it
# on your watch: open apps/watch/AnyAssistantWatch.xcodeproj, choose your watch and Run.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
xcodegen generate --quiet
xcodebuild -project AnyAssistantWatch.xcodeproj -scheme AnyAssistant -destination 'generic/platform=watchOS' \
  -quiet build CODE_SIGNING_ALLOWED=NO
echo "Built. To install: open $HERE/AnyAssistantWatch.xcodeproj, choose your Apple Watch and Run."
