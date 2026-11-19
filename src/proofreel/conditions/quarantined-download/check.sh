#!/bin/sh
app=~/Downloads/"$(cat app-name)"
[ -d "$app" ] || { echo "No app at $app."; exit 1; }
flag=$(xattr -p com.apple.quarantine "$app" 2>/dev/null) || { echo "$app has no quarantine flag."; exit 1; }
case "$flag" in 00[012389ab]?\;*) ;; *) echo "$app was approved or changed: $flag"; exit 1 ;; esac
id=${flag##*;}
url=$(sqlite3 ~/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2 \
  "select LSQuarantineDataURLString from LSQuarantineEvent where LSQuarantineEventIdentifier = '$id'")
[ -n "$url" ] || { echo "$app has no download record for $id."; exit 1; }
echo "Quarantined in Downloads: $app ($flag, from $url)"
