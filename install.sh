#!/bin/sh
# Install or upgrade the Logseq DB widget for the current user.
set -eu
PKG="$(cd "$(dirname "$0")" && pwd)/package"
if ! command -v kpackagetool6 >/dev/null 2>&1; then
    echo "kpackagetool6 not found. This widget needs KDE Plasma 6." >&2
    exit 1
fi
if kpackagetool6 -t Plasma/Applet -u "$PKG" 2>/dev/null; then
    echo "Upgraded. Restart Plasma (systemctl --user restart plasma-plasmashell) to load the new version."
else
    kpackagetool6 -t Plasma/Applet -i "$PKG"
    echo "Installed. Add 'Logseq DB' from Add or Manage Widgets."
fi
