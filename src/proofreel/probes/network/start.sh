set -eu
proxy="$PROOFREEL_HOST_FOR_GUEST:$PROOFREEL_PORT"
tries=0
until curl -sf -x "http://$proxy" http://mitm.it/cert/pem -o ca.pem; do
  tries=$((tries + 1))
  [ "$tries" -lt 40 ] || { echo "The proxy at $proxy did not answer in 20 s."; exit 1; }
  sleep 0.5
done
sudo -n install -m 644 ca.pem /usr/local/share/ca-certificates/proofreel-network.crt
sudo -n update-ca-certificates >/dev/null 2>&1
der=$(openssl x509 -in ca.pem -outform DER | base64 -w0)
printf '{"ProxySettings": {"ProxyMode": "fixed_servers", "ProxyServer": "%s"}, "CACertificates": ["%s"]}\n' "$proxy" "$der" \
  | sudo -n tee /etc/chromium/policies/managed/proofreel-network.json >/dev/null
# WHY: a running Chromium reads a changed policy file once it is 5 s old.
if pgrep -x chromium >/dev/null; then sleep 6; fi
