#!/usr/bin/env bash
# Copy this plugin into StreamController's plugin directory.
#
# StreamController loads plugins from its flatpak data dir, NOT from this
# repo. Editing files here changes nothing until they are copied over and
# the app is restarted -- plugins are imported once, at startup.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${STREAMCONTROLLER_PLUGIN_DIR:-\
$HOME/.var/app/com.core447.StreamController/data/plugins/com_z19r_DialCommand}"

if [[ ! -d "$(dirname "$DEST")" ]]; then
  echo "error: plugin dir not found: $(dirname "$DEST")" >&2
  echo "Is StreamController installed as a flatpak?" >&2
  exit 1
fi

mkdir -p "$DEST"
rsync -a --delete \
  --exclude='__pycache__' \
  "$SRC/main.py" "$SRC/manifest.json" "$SRC/__init__.py" \
  "$SRC/actions" "$SRC/assets" "$SRC/locales" \
  "$DEST/"

# Drop stale bytecode; the flatpak runs a different Python than the host.
find "$DEST" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

echo "deployed to $DEST"
echo "now restart StreamController to load it:"
echo "  pkill -f StreamController && flatpak run com.core447.StreamController &"
