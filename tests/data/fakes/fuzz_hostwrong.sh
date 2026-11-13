#!/bin/bash
# Fake fuzz program: right on the device (42), 5 when offload is disabled
# (a host path that disagrees).
if [ "$OMP_TARGET_OFFLOAD" = disabled ]; then
  echo "RESULT checksum=5 ran_on_host=1"
else
  echo "RESULT checksum=42 ran_on_host=0"
fi
