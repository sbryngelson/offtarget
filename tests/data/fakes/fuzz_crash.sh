#!/bin/bash
# Fake fuzz program: dies with SIGSEGV unless offload is disabled.
if [ "$OMP_TARGET_OFFLOAD" = disabled ]; then
  echo "RESULT checksum=42 ran_on_host=1"
  exit 0
fi
kill -SEGV $$
