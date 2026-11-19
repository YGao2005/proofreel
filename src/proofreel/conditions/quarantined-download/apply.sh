#!/bin/sh
set -eu
mount=$(mktemp -d)
hdiutil attach -nobrowse -readonly -mountpoint "$mount" app.dmg >/dev/null
app=$(ls -d "$mount"/*.app | head -1)
name=$(basename "$app")
rm -rf ~/Downloads/"$name"
ditto "$app" ~/Downloads/"$name"
hdiutil detach "$mount" >/dev/null
id=$(uuidgen)
now=$(date +%s)
sqlite3 ~/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2 "insert into LSQuarantineEvent
  (LSQuarantineEventIdentifier, LSQuarantineTimeStamp, LSQuarantineAgentBundleIdentifier, LSQuarantineAgentName,
   LSQuarantineDataURLString, LSQuarantineTypeNumber, LSQuarantineOriginURLString)
  values ('$id', $((now - 978307200)), 'com.apple.Safari', 'Safari', 'https://downloads.example.com/app.dmg', 0,
          'https://example.com/')"
xattr -w com.apple.quarantine "0083;$(printf '%x' "$now");Safari;$id" ~/Downloads/"$name"
echo "$name" > app-name
