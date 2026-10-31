#!/bin/sh
# While developing: puts the build into /Applications and opens it (instead of the .dmg by hand).
#
#   apps/mac/install-dev.sh            the last build (apps/mac/build/AnyAssistant.app)
#   apps/mac/install-dev.sh --build    builds it first (apps/mac/build.sh: signed, not notarized)
#
# It quits AnyAssistant (its server stops with it), copies the app over the one in
# /Applications (only AnyAssistant.app: nothing else there is touched) and opens it again.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/build/AnyAssistant.app"
TARGET="/Applications/AnyAssistant.app"

[ "$1" = "--build" ] && "$HERE/build.sh"
[ -d "$APP" ] || { echo "No build yet: apps/mac/install-dev.sh --build"; exit 1; }

if pgrep -f "$TARGET/Contents/MacOS/AnyAssistant" > /dev/null; then
  echo "Quitting AnyAssistant…"
  osascript -e 'tell application id "com.anyassistant.app" to quit' 2>/dev/null || true
  i=0
  while pgrep -f "$TARGET/Contents/MacOS/AnyAssistant" > /dev/null && [ $i -lt 30 ]; do sleep 0.5; i=$((i + 1)); done
fi
hdiutil detach /Volumes/AnyAssistant > /dev/null 2>&1 || true  # an open .dmg would keep the old one around
echo "Installing in $TARGET…"
rsync -a --delete "$APP/" "$TARGET/"
open "$TARGET"
echo "Done: AnyAssistant $(defaults read "$TARGET/Contents/Info" CFBundleVersion) is open."
