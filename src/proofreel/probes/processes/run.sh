#!/bin/sh
if [ "$(uname)" = Darwin ]; then
  [ -x ./procs ] || { echo '{"unavailable": "procs was not built: the host needs swiftc"}'; exit 0; }
  exec ./procs
fi
command -v python3 >/dev/null || { echo '{"unavailable": "the guest has no python3"}'; exit 0; }
exec python3 -u procs.py
