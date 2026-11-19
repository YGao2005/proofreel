#!/bin/sh
devices=$(system_profiler SPAudioDataType)
inputs=$(printf '%s\n' "$devices" | grep -c "Input Channels")
all=$(printf '%s\n' "$devices" | grep -c "Transport:")
if [ "$inputs" -ne 0 ]; then
  echo "Core Audio lists $inputs device(s) with input:"
  printf '%s\n' "$devices"
  exit 1
fi
echo "No input device: Core Audio lists $all device(s), none with input channels."
