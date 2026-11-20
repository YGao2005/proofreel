#!/bin/sh
set -eu
case "$RATE" in 16000|24000) ;; *) echo "RATE must be 16000 or 24000, not $RATE." >&2; exit 1 ;; esac
bundle="$OUT/ProofreelHeadset.driver/Contents"
mkdir -p "$bundle/MacOS"
cp Info.plist "$bundle/Info.plist"
clang -O2 -bundle -arch arm64 -mmacosx-version-min=14.0 -DCALL_RATE="$RATE.0" -framework CoreAudio -framework CoreFoundation \
  headset.c -o "$bundle/MacOS/ProofreelHeadset"
codesign --force --sign - "$OUT/ProofreelHeadset.driver"
