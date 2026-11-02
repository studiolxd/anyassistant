#!/bin/sh
# Publishes a version, from this Mac: apps/release.sh v0.2.0
#
#   1. Checks: main, nothing uncommitted, pushed; the tag is new; its notes exist
#      (docs/versiones/v0.2.0.md: what this version brings, in Spanish, for people); the tests pass.
#   2. Tags it and pushes the tag: GitHub Actions (.github/workflows/release.yml) builds the Windows
#      and Linux app with that version, the program alone and install.sh, and makes the release with
#      those notes.
#   3. Meanwhile, the Mac's app: built, signed and notarized here (apps/mac/build.sh --release, with
#      this version), then added to that release once it exists, with its appcast.xml (apps/mac/
#      appcast.py): what the installed Macs' Sparkle reads to offer it, its .dmg signed with the key
#      in this Mac's Keychain (made once by Sparkle's generate_keys; keep a copy: docs/versiones).
#
# The phone apps go apart: TestFlight (apps/apple/testflight.sh) and Android's APK.
set -e
TAG="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "$TAG" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' || { echo "Usage: apps/release.sh v0.2.0"; exit 1; }
VERSION="${TAG#v}"
NOTES="docs/versiones/$TAG.md"

# 1. Checks
[ "$(git branch --show-current)" = "main" ] || { echo "On main only."; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "There are uncommitted changes:"; git status --short; exit 1; }
git fetch --quiet origin main --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "main isn't pushed (or is behind origin): git push first."; exit 1; }
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then echo "$TAG already exists."; exit 1; fi
if [ ! -f "$NOTES" ]; then
  PREVIOUS="$(git describe --tags --abbrev=0 --match 'v*' 2>/dev/null || true)"
  echo "Its notes are missing: $NOTES (what this version brings). Since ${PREVIOUS:-the beginning}:"
  git log --format='  - %s' ${PREVIOUS:+$PREVIOUS..}HEAD | cut -c1-160
  exit 1
fi
echo "Running the tests…"
if command -v uv >/dev/null 2>&1; then uv run pytest -q >/dev/null; else .venv/bin/python -m pytest -q >/dev/null; fi

# 2. The tag: GitHub builds Windows, Linux and the program, and makes the release
git tag -a "$TAG" -m "AnyAssistant $TAG"
git push --quiet origin "$TAG"
echo "Tagged $TAG: GitHub is building Windows and Linux."

# 3. The Mac's app, meanwhile
RELEASE_VERSION="$VERSION" "$ROOT/apps/mac/build.sh" --release
DMG="$ROOT/apps/mac/build/AnyAssistant-$VERSION-mac.dmg"
cp "$ROOT/apps/mac/build/AnyAssistant.dmg" "$DMG"
SIGNED="$("$ROOT/apps/mac/.build/artifacts/sparkle/Sparkle/bin/sign_update" "$DMG")"  # the key in the Keychain
BUILD="$(plutil -extract CFBundleVersion raw "$ROOT/apps/mac/build/AnyAssistant.app/Contents/Info.plist")"
APPCAST="$ROOT/apps/mac/build/appcast.xml"
python3 "$ROOT/apps/mac/appcast.py" "$NOTES" "$TAG" "$VERSION" "$BUILD" "$SIGNED" "$APPCAST"

echo "Waiting for GitHub's release…"
RUN=""
for _ in $(seq 1 60); do
  RUN="$(gh run list --workflow release.yml --branch "$TAG" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
  [ -n "$RUN" ] && break
  sleep 5
done
[ -n "$RUN" ] || { echo "GitHub's build didn't start. The .dmg is at $DMG: gh release upload $TAG \"$DMG\""; exit 1; }
gh run watch "$RUN" --exit-status >/dev/null || { echo "GitHub's build failed: gh run view $RUN --log-failed. The .dmg: $DMG"; exit 1; }
gh release upload "$TAG" "$DMG" "$APPCAST"
echo "Published: $(gh release view "$TAG" --json url -q .url)"
