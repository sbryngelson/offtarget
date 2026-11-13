#!/bin/bash
# Fake fuzz program: never finishes on the device.
if [ "$OMP_TARGET_OFFLOAD" = disabled ]; then
  echo "RESULT checksum=42 ran_on_host=1"; exit 0
fi
sleep 30
