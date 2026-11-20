#!/bin/sh
if [ "$(uname)" = Darwin ] && ! xcode-select -p >/dev/null 2>&1 || ! command -v python3 >/dev/null; then
  echo '{"unavailable": "the guest has no python3 (on macOS, install the Command Line Tools)"}'
  exit 0
fi
exec python3 -u procs.py
