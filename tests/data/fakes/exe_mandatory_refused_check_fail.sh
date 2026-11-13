#!/bin/bash
# Fake program: fails under OMP_TARGET_OFFLOAD=mandatory; without it, runs
# on the host and its check fails.
if [ "$OMP_TARGET_OFFLOAD" = "mandatory" ]; then
  exit 1
fi
echo "RESULT ran_on_host=1 check=fail"
