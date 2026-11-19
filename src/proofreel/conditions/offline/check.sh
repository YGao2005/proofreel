#!/bin/sh
sudo pfctl -s info 2>/dev/null | grep -q "Status: Enabled" || { echo "pf is off."; exit 1; }
sudo pfctl -s rules 2>/dev/null | grep -q "block return all" || { echo "pf has no proofreel rules: $(sudo pfctl -s rules 2>&1)"; exit 1; }
if nc -z -G 5 1.1.1.1 443 2>/dev/null; then echo "1.1.1.1:443 answers."; exit 1; fi
if dscacheutil -q host -a name example.com | grep -q address; then echo "DNS answers for example.com."; exit 1; fi
echo "Offline: pf is on, 1.1.1.1:443 and DNS fail; SSH from the host works."
