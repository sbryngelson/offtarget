#!/bin/bash
# Fake fuzz program: right everywhere (42), but the host run takes 3 s.
if [ "$OMP_TARGET_OFFLOAD" = disabled ]; then
  sleep 3; echo "RESULT checksum=42 ran_on_host=1"
else
  echo "RESULT checksum=42 ran_on_host=0"
fi
