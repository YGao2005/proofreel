#!/bin/sh
dmg="$(pwd)/app.dmg"
for _ in $(seq 20); do
  volume=$(hdiutil info | awk -v dmg="$dmg" '$0 ~ "image-path" {on = index($0, dmg) > 0} on && /\/Volumes\// {sub(/.*\t/, ""); print; exit}')
  [ -n "$volume" ] && break
  sleep 1
done
[ -n "$volume" ] || { echo "The DMG is not mounted."; exit 1; }
app=$(ls -d "$volume"/*.app 2>/dev/null | head -1)
[ -n "$app" ] || { echo "No app at the top of $volume."; exit 1; }
echo "Mounted from the DMG: $app"
