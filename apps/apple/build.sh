#!/bin/sh
# The Apple apps (iPhone and iPad, and the Apple Watch): makes the Xcode project (xcodegen) and
# checks they build. To try them: apps/apple/run.sh (on the iPhone connected by cable), or
# apps/apple/testflight.sh.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
xcodegen generate --quiet
xcodebuild -project AnyAssistant.xcodeproj -scheme AnyAssistant -destination 'generic/platform=iOS' \
  -quiet build CODE_SIGNING_ALLOWED=NO
echo "Built: $HERE/AnyAssistant.xcodeproj"
