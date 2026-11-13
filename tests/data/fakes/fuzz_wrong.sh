#!/bin/bash
# Fake fuzz program: wrong checksum (7) on the device, 42 on the host.
if [ "$OMP_TARGET_OFFLOAD" = disabled ]; then
  echo "RESULT checksum=42 ran_on_host=1"
else
  echo "RESULT checksum=7 ran_on_host=0"
fi
