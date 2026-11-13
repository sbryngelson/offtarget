#!/bin/bash
# Fake fuzz program: aborts under OMP_TARGET_OFFLOAD=mandatory, runs on the
# host (right checksum) otherwise.
if [ "$OMP_TARGET_OFFLOAD" = mandatory ]; then
  echo "offload refused" >&2
  exit 1
fi
echo "RESULT checksum=42 ran_on_host=1"
