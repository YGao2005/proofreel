#!/bin/sh
command -v python3 >/dev/null || { echo '{"unavailable": "the guest has no python3"}'; exit 0; }
exec python3 -u procs.py
