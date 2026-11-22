#!/usr/bin/env bash
# Install proofreel. Usage: install.sh <version input> <action ref> <action path>
# A version input wins. Else the action tag decides: v1.2.2 is exact, v1 is the newest 1.x, and a branch, a SHA,
# or a local action installs the code of the action itself.
set -euo pipefail
v="${1:-}" ref="${2:-}" path="$3"
if [ -z "$v" ]; then
  case "$ref" in
    v[0-9]*.[0-9]*.[0-9]*) v="${ref#v}" ;;
    v[0-9]*) v="major:${ref#v}" ;;
    *) v=source ;;
  esac
fi
case "$v" in
  source) spec="$path" ;;
  latest) spec=proofreel ;;
  major:*) spec="proofreel>=${v#major:},<$(( ${v#major:} + 1 ))" ;;
  *) spec="proofreel==$v" ;;
esac
python -m pip install --quiet "$spec"
proofreel --version
