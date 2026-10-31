#!/bin/sh
# Installs AnyAssistant on this Mac: the program, its own Python (uv), and then the
# steps of bin/anyassistant setup (language, name, LLM, models, starting with the Mac…).
#
#   ./install.sh                   asks each step (Enter keeps what comes)
#   ./install.sh --defaults        everything as it comes, no questions
#   ./install.sh --json …          for the app's window (one JSON event per line)
#   --to <folder>                  where the program goes (default ~/Applications/AnyAssistant)
#   --data <folder> --cache <folder>   your data and what can be rebuilt
#   --set key=value                an answer given in advance (e.g. --set llm=apple)
#   --update                       only the program, its packages, bridges and models, then
#                                  restart (what bin/anyassistant update runs)
#
# Run again, it updates the program and keeps your data. Nothing needs administrator rights.
set -e

SOURCE="$(cd "$(dirname "$0")" && pwd)"
TO="$HOME/Applications/AnyAssistant"
DATA="$HOME/Library/Application Support/AnyAssistant"
CACHE="$HOME/Library/Caches/AnyAssistant"
PASS=""
UPDATE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --update) UPDATE=1; shift ;;
    --to) TO="$2"; shift 2 ;;
    --data) DATA="$2"; shift 2 ;;
    --cache) CACHE="$2"; shift 2 ;;
    *) PASS="$PASS $(printf '%s' "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/\$/'/")"; shift ;;
  esac
done
JSON=0; case "$PASS" in *"'--json'"*) JSON=1 ;; esac
say() { [ $JSON = 1 ] && printf '{"event": "install", "text": "%s"}\n' "$1" || echo "$1"; }

[ "$(uname)" = "Darwin" ] || { say "AnyAssistant needs a Mac for now."; exit 1; }

# Its own Python, without touching the system's (and no administrator rights).
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  say "Installing uv (Python and its packages)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

# The program: the committed files of this copy (a release will bring them packed).
say "Copying the program to $TO…"
mkdir -p "$TO" "$DATA" "$CACHE"
FRESH="$(mktemp -d)"
if [ -d "$SOURCE/.git" ]; then
  git -C "$SOURCE" archive HEAD | tar -x -C "$FRESH"
else
  (cd "$SOURCE" && tar -cf - --exclude .venv --exclude .build --exclude install.env .) | tar -x -C "$FRESH"
fi
# What a new version removed goes too; its Python, its place and its bridges stay.
rsync -a --delete --exclude .venv --exclude install.env --exclude native "$FRESH/" "$TO/"
rm -rf "$FRESH"
[ -d "$SOURCE/native" ] && cp -R "$SOURCE/native" "$TO/"  # the Swift bridges, if already built
cat > "$TO/install.env" <<ENV
# Where this copy keeps your data and what can be rebuilt (server/paths.py, bin/anyassistant).
ANYASSISTANT_SOURCE="$SOURCE"
ANYASSISTANT_HOME="$DATA"
ANYASSISTANT_CACHE="$CACHE"
ENV

say "Preparing Python…"
(cd "$TO" && "$UV" sync --frozen --no-dev --quiet)

eval "set -- $PASS"
if [ $UPDATE = 1 ]; then
  say "Updating what it needs…"
  "$TO/bin/anyassistant" setup "$@" packages bridges models || exit 1
  "$TO/bin/anyassistant" restart 2>/dev/null || true  # the new code (if it was running)
  say "Updated."
  exit 0
fi
say "Setting it up…"
exec "$TO/bin/anyassistant" setup "$@"
