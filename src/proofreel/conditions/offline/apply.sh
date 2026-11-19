#!/bin/sh
set -eu
sudo tee /etc/proofreel-offline.conf >/dev/null <<'RULES'
set skip on lo0
block return all
pass in proto tcp from any to any port 22 flags any no state
pass out proto tcp from any port 22 to any flags any no state
RULES
sudo tee /Library/LaunchDaemons/dev.proofreel.offline.plist >/dev/null <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>dev.proofreel.offline</string>
	<key>ProgramArguments</key>
	<array><string>/sbin/pfctl</string><string>-e</string><string>-f</string><string>/etc/proofreel-offline.conf</string></array>
	<key>RunAtLoad</key><true/>
</dict>
</plist>
PLIST
sudo pfctl -e -f /etc/proofreel-offline.conf 2>/dev/null || sudo pfctl -f /etc/proofreel-offline.conf 2>/dev/null
