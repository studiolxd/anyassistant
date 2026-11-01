#!/bin/sh
# Builds AnyAssistant.app and AnyAssistant.dmg (apps/mac/build/): the menu bar app, with
# the program (the committed version, its Swift bridges already built) and uv inside.
#
#   apps/mac/build.sh            while developing: signed with the Developer ID if this Mac has
#                                one (the same app for macOS each time: its Local Network permission
#                                stays), not notarized (not needed for a build opened on this Mac)
#   apps/mac/build.sh --release  to share it: signed and notarized by Apple (a few minutes)
#   SIGN="…" NOTARY=…            another identity, or another notarytool profile
#                                (made once with `xcrun notarytool store-credentials anyassistant`)
set -e
RELEASE=0; [ "$1" = "--release" ] && RELEASE=1
if [ -z "$SIGN" ]; then  # the Developer ID of this Mac, if there is one; else ad hoc
  SIGN="$(security find-identity -v -p codesigning | sed -n 's/.*"\(Developer ID Application: [^"]*\)".*/\1/p' | head -1)"
fi
[ $RELEASE = 1 ] && NOTARY="${NOTARY:-anyassistant}" || NOTARY=""
[ $RELEASE = 1 ] && [ -z "$SIGN" ] && { echo "A release needs a Developer ID Application certificate."; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$HERE/build"
APP="$OUT/AnyAssistant.app"
VERSION="$(git -C "$ROOT" rev-list --count HEAD)-$(git -C "$ROOT" rev-parse --short HEAD)"  # as install.sh

echo "Building the app…"
(cd "$HERE" && swift build -c release --quiet)
rm -rf "$OUT" && mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$HERE/.build/release/AnyAssistant" "$APP/Contents/MacOS/"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>AnyAssistant</string>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleLocalizations</key><array><string>en</string><string>es</string></array>
  <key>CFBundleDisplayName</key><string>AnyAssistant</string>
  <key>CFBundleIdentifier</key><string>com.anyassistant.app</string>
  <key>CFBundleExecutable</key><string>AnyAssistant</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSLocalNetworkUsageDescription</key>
  <string>AnyAssistant talks to your tablet or phone on this network: its microphone, camera and screen.</string>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSMicrophoneUsageDescription</key>
  <string>So you can talk to the assistant on this Mac.</string>
  <key>NSCameraUsageDescription</key>
  <string>For «what do you see?»: the assistant looks only while its window is open.</string>
</dict></plist>
PLIST

cp -R "$HERE/Resources/"*.lproj "$APP/Contents/Resources/"  # its texts in each language
cp "$HERE/Resources/AppIcon.icns" "$APP/Contents/Resources/"  # its icon (apps/icon/make.py)

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
IDENTITY="${SIGN:--}"
STAMP=""; [ "$IDENTITY" != "-" ] && STAMP="--timestamp"
# What it carries inside first (Apple notarizes only if every binary is signed), then the app.
for binary in "$APP/Contents/Resources/uv" "$PROGRAM/native/"*; do
  codesign --force --options runtime $STAMP --sign "$IDENTITY" "$binary"
done
codesign --force --options runtime $STAMP --entitlements "$HERE/AnyAssistant.entitlements" --sign "$IDENTITY" "$APP"
codesign --verify --strict "$APP"

echo "Making the .dmg…"
STAGE="$OUT/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname AnyAssistant -srcfolder "$STAGE" -ov -format UDZO "$OUT/AnyAssistant.dmg" > /dev/null
rm -rf "$STAGE"
if [ "$IDENTITY" != "-" ]; then
  codesign --force $STAMP --sign "$IDENTITY" "$OUT/AnyAssistant.dmg"
  if [ -n "$NOTARY" ]; then
    echo "Notarizing (Apple checks it; a few minutes)…"
    xcrun notarytool submit "$OUT/AnyAssistant.dmg" --keychain-profile "$NOTARY" --wait
    xcrun stapler staple "$OUT/AnyAssistant.dmg"
  fi
fi
echo "Done: $OUT/AnyAssistant.dmg ($(du -h "$OUT/AnyAssistant.dmg" | cut -f1))"
