#!/bin/bash
# Fake fuzz program: right on the device (42), dies with SIGSEGV when
# offload is disabled (a host-path failure).
if [ "$OMP_TARGET_OFFLOAD" = disabled ]; then
  kill -SEGV $$
fi
echo "RESULT checksum=42 ran_on_host=0"
