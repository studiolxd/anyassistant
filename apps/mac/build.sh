#!/bin/sh
# Builds AnyAssistant.app and AnyAssistant.dmg (apps/mac/build/): the menu bar app, with
# the program (the committed version, its Swift bridges already built) and uv inside.
#
#   apps/mac/build.sh            signed for this Mac only (ad hoc)
#   SIGN="Developer ID Application: …" apps/mac/build.sh    to share it (then notarize)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$HERE/build"
APP="$OUT/AnyAssistant.app"
VERSION="$(git -C "$ROOT" rev-parse --short HEAD)"

echo "Building the app…"
(cd "$HERE" && swift build -c release --quiet)
rm -rf "$OUT" && mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$HERE/.build/release/AnyAssistant" "$APP/Contents/MacOS/"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>AnyAssistant</string>
  <key>CFBundleDisplayName</key><string>AnyAssistant</string>
  <key>CFBundleIdentifier</key><string>com.anyassistant.app</string>
  <key>CFBundleExecutable</key><string>AnyAssistant</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSLocalNetworkUsageDescription</key>
  <string>AnyAssistant talks to your tablet or phone on this network: its microphone, camera and screen.</string>
</dict></plist>
PLIST

echo "Adding the program ($VERSION)…"
PROGRAM="$APP/Contents/Resources/program"
mkdir -p "$PROGRAM"
git -C "$ROOT" archive HEAD | tar -x -C "$PROGRAM"
echo "$VERSION" > "$PROGRAM/VERSION"
echo "Building the Swift bridges…"
(cd "$PROGRAM" && "$ROOT/.venv/bin/python" server/swift.py prebuild > /dev/null 2>&1)
UV_BIN="$(command -v uv || echo "$HOME/.local/bin/uv")"
cp "$UV_BIN" "$APP/Contents/Resources/uv"

echo "Signing…"
codesign --force --deep --options runtime --sign "${SIGN:--}" "$APP"

echo "Making the .dmg…"
STAGE="$OUT/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname AnyAssistant -srcfolder "$STAGE" -ov -format UDZO "$OUT/AnyAssistant.dmg" > /dev/null
rm -rf "$STAGE"
echo "Done: $OUT/AnyAssistant.dmg ($(du -h "$OUT/AnyAssistant.dmg" | cut -f1))"
