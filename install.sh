#!/bin/sh
# Installs AnyAssistant on this Mac or Linux computer (Windows: its app): the program, its own Python (uv), and then the
# steps of bin/anyassistant setup (language, name, LLM, models, starting with the Mac…).
#
#   ./install.sh                   asks each step (Enter keeps what comes)
#   curl -fsSL https://github.com/studiolxd/anyassistant/releases/latest/download/install.sh | sh
#                                  without a copy: the program comes from the latest release
#   ./install.sh --defaults        everything as it comes, no questions
#   ./install.sh --json …          for the app's window (one JSON event per line)
#   --to <folder>                  where the program goes (default ~/Applications/AnyAssistant;
#                                  on Linux ~/.local/opt/AnyAssistant)
#   --data <folder> --cache <folder>   your data and what can be rebuilt
#   --set key=value                an answer given in advance (e.g. --set llm=apple)
#   --no-setup                     only the program and its Python (the app asks the questions)
#   --force                        install even an older version than the installed one
#   --update                       only the program, its packages, bridges and models, then
#                                  restart (what bin/anyassistant update runs)
#
# Run again, it updates the program and keeps your data. Nothing needs administrator rights.
set -e

SOURCE="$(cd "$(dirname "$0")" && pwd)"
case "$(uname)" in
  Darwin)
    TO="$HOME/Applications/AnyAssistant"
    DATA="$HOME/Library/Application Support/AnyAssistant"
    CACHE="$HOME/Library/Caches/AnyAssistant" ;;
  Linux)  # where Linux keeps them (XDG)
    TO="$HOME/.local/opt/AnyAssistant"
    DATA="${XDG_DATA_HOME:-$HOME/.local/share}/AnyAssistant"
    CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/AnyAssistant" ;;
  *) echo "This installer is for macOS and Linux (on Windows, the AnyAssistant app)."; exit 1 ;;
esac

# On its own (curl … | sh, or this file alone): the program comes from the latest release (its
# AnyAssistant-program.tar.gz: the server's files and its VERSION), and that copy installs it.
if [ ! -f "$SOURCE/server/main.py" ]; then
  RELEASE="${ANYASSISTANT_RELEASE:-https://github.com/studiolxd/anyassistant/releases/latest/download}"
  FETCHED="$(mktemp -d)"
  echo "Downloading AnyAssistant…"
  curl -fsSL -o "$FETCHED/program.tar.gz" "$RELEASE/AnyAssistant-program.tar.gz" \
    || { echo "It couldn't download AnyAssistant ($RELEASE/AnyAssistant-program.tar.gz)."; exit 1; }
  tar -xzf "$FETCHED/program.tar.gz" -C "$FETCHED"
  ANYASSISTANT_FROM_RELEASE=1 exec sh "$FETCHED/program/install.sh" "$@"
fi
PASS=""
UPDATE=0
SETUP=1
while [ $# -gt 0 ]; do
  case "$1" in
    --no-setup) SETUP=0; shift ;;
    --force) FORCE=1; shift ;;
    --update) UPDATE=1; shift ;;
    --to) TO="$2"; shift 2 ;;
    --data) DATA="$2"; shift 2 ;;
    --cache) CACHE="$2"; shift 2 ;;
    *) PASS="$PASS $(printf '%s' "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/\$/'/")"; shift ;;
  esac
done
JSON=0; case "$PASS" in *"'--json'"*) JSON=1 ;; esac
say() { [ $JSON = 1 ] && printf '{"event": "install", "text": "%s"}\n' "$1" || echo "$1"; }

# Its own Python, without touching the system's (and no administrator rights).
# $UV: the one the app brings; otherwise the computer's, or it installs it.
if [ -z "$UV" ]; then
  if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
    say "Installing uv (Python and its packages)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  fi
  UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
fi
export UV

# The program: the committed files of this copy (a release will bring them packed).
say "Copying the program to $TO…"
mkdir -p "$TO" "$DATA" "$CACHE"
FRESH="$(mktemp -d)"
if [ -d "$SOURCE/.git" ]; then
  git -C "$SOURCE" archive HEAD | tar -x -C "$FRESH"
  # Which version is installed, «<commits>-<hash>»: the app updates only to a newer one.
  echo "$(git -C "$SOURCE" rev-list --count HEAD)-$(git -C "$SOURCE" rev-parse --short HEAD)" > "$FRESH/VERSION"
else
  (cd "$SOURCE" && tar -cf - --exclude .venv --exclude .build --exclude install.env .) | tar -x -C "$FRESH"
fi
# Never back to an older version (an app bringing an old copy, another checkout) unless --force.
number() { [ -f "$1" ] && cut -d- -f1 "$1" | tr -dc '0-9' || echo 0; }
NEW=$(number "$FRESH/VERSION"); OLD=$(number "$TO/VERSION")
if [ "${FORCE:-0}" != 1 ] && [ -n "$NEW" ] && [ -n "$OLD" ] && [ "$NEW" -lt "$OLD" ] 2>/dev/null; then
  say "The installed version ($(cat "$TO/VERSION")) is newer than this one ($(cat "$FRESH/VERSION")): left as it is (--force to install it anyway)."
  rm -rf "$FRESH"
  exit 0
fi
# What a new version removed goes too; its Python, its place and its bridges stay.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude .venv --exclude install.env --exclude native "$FRESH/" "$TO/"
else  # some Linux have no rsync: the same by hand
  find "$TO" -mindepth 1 -maxdepth 1 ! -name .venv ! -name install.env ! -name native -exec rm -rf {} +
  cp -a "$FRESH/." "$TO/"
fi
rm -rf "$FRESH"
[ -d "$SOURCE/native" ] && cp -R "$SOURCE/native" "$TO/"  # the Swift bridges, if already built
cat > "$TO/install.env" <<ENV
# Where this copy keeps your data and what can be rebuilt (server/paths.py, bin/anyassistant).
# ANYASSISTANT_SOURCE: the copy it came from («anyassistant update» installs from there); empty: a
# release (curl … | sh: its copy was temporary), so it updates from the latest release.
ANYASSISTANT_SOURCE="$([ -n "$ANYASSISTANT_FROM_RELEASE" ] || printf '%s' "$SOURCE")"
ANYASSISTANT_HOME="$DATA"
ANYASSISTANT_CACHE="$CACHE"
ENV

say "Preparing Python…"
# --inexact: the plugins' packages already there stay (its «packages» step sets them as they should be).
(cd "$TO" && "$UV" sync --frozen --no-dev --inexact --quiet)

# «anyassistant» in a terminal: ~/.local/bin is in the PATH on most systems (uv's installer adds it).
# Not over a file of someone else's there, only over a link.
LINK="$HOME/.local/bin/anyassistant"
if [ ! -e "$LINK" ] || [ -L "$LINK" ]; then
  mkdir -p "$HOME/.local/bin" && ln -sf "$TO/bin/anyassistant" "$LINK"
fi

eval "set -- $PASS"
if [ $SETUP = 0 ]; then
  say "Ready for its setup."
  exit 0
fi
if [ $UPDATE = 1 ]; then
  say "Updating what it needs…"
  "$TO/bin/anyassistant" setup "$@" packages bridges models || exit 1
  "$TO/bin/anyassistant" restart 2>/dev/null || true  # the new code (if it was running)
  say "Updated."
  exit 0
fi
say "Setting it up…"
exec "$TO/bin/anyassistant" setup "$@"
