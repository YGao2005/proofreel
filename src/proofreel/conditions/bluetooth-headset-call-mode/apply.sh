#!/bin/sh
set -eu
sudo rm -rf /Library/Audio/Plug-Ins/HAL/ProofreelHeadset.driver
sudo cp -R ProofreelHeadset.driver /Library/Audio/Plug-Ins/HAL/
sudo killall coreaudiod
for _ in $(seq 30); do ./probe set-default-input proofreel.headset && exit 0; sleep 1; done
echo "The headset did not show up in Core Audio." >&2
exit 1
