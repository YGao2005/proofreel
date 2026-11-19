#!/bin/sh
set -eu
if [ -e /Library/Audio/Plug-Ins/HAL/ProofreelHeadset.driver ]; then
  sudo rm -rf /Library/Audio/Plug-Ins/HAL/ProofreelHeadset.driver
  sudo killall coreaudiod
  sleep 3
fi
