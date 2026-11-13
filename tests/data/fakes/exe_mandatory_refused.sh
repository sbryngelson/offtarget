#!/bin/bash
# Fake program: fails under OMP_TARGET_OFFLOAD=mandatory, runs on the host
# without it.
if [ "$OMP_TARGET_OFFLOAD" = "mandatory" ]; then
  echo "fake: offload failed while offloading is mandatory" >&2
  exit 1
fi
echo "RESULT ran_on_host=1 check=pass"
