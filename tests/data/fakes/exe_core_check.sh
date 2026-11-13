#!/bin/bash
# Fake program: passes only if core dumps are disabled and HSA_XNACK and
# TMPDIR are set by the harness.
if [ "$(ulimit -c)" = "0" ] && [ -n "$HSA_XNACK" ] && [ -d "$TMPDIR" ]; then
  echo "RESULT ran_on_host=0 check=pass"
else
  echo "RESULT ran_on_host=0 check=fail"
fi
