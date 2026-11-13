#!/bin/bash
# Fake fuzz program: the first device run is wrong, later ones are right
# (a counter file in the working directory).
if [ "$OMP_TARGET_OFFLOAD" = disabled ]; then
  echo "RESULT checksum=42 ran_on_host=1"; exit 0
fi
n=$(cat flaky.count 2>/dev/null || echo 0)
echo $((n + 1)) > flaky.count
if [ "$n" = 0 ]; then echo "RESULT checksum=9 ran_on_host=0"
else echo "RESULT checksum=42 ran_on_host=0"; fi
