#!/bin/sh
set -eu
[ -f "$DMG" ] || { echo "No DMG at $DMG." >&2; exit 1; }
cp "$DMG" "$OUT/app.dmg"
