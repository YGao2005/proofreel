policy=/etc/chromium/policies/managed/proofreel-network.json
ca=/usr/local/share/ca-certificates/proofreel-network.crt
sudo -n rm -f "$policy" "$ca"
sudo -n update-ca-certificates --fresh >/dev/null 2>&1
rm -f ca.pem
# WHY: a running Chromium reads a changed policy file once it is 5 s old.
if pgrep -x chromium >/dev/null; then sleep 6; fi
[ ! -e "$policy" ] && [ ! -e "$ca" ] && [ ! -L /etc/ssl/certs/proofreel-network.pem ]
