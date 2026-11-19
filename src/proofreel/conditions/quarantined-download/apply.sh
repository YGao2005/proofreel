#!/bin/sh
set -eu
mount=$(mktemp -d)
hdiutil attach -nobrowse -readonly -mountpoint "$mount" app.dmg >/dev/null
app=$(ls -d "$mount"/*.app | head -1)
rm -rf ~/Downloads/"$(basename "$app")"
ditto "$app" ~/Downloads/"$(basename "$app")"
hdiutil detach "$mount" >/dev/null
xattr -w com.apple.quarantine "0083;$(printf '%x' "$(date +%s)");Safari;" ~/Downloads/"$(basename "$app")"
basename "$app" > app-name
