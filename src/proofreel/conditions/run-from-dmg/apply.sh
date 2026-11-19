#!/bin/sh
set -eu
dmg="$(pwd)/app.dmg"
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/dev.proofreel.run-from-dmg.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>dev.proofreel.run-from-dmg</string>
	<key>ProgramArguments</key>
	<array><string>/usr/bin/hdiutil</string><string>attach</string><string>$dmg</string></array>
	<key>RunAtLoad</key><true/>
</dict>
</plist>
PLIST
hdiutil info | grep -q "$dmg" || hdiutil attach "$dmg" >/dev/null
