#!/bin/bash
# The path-dependent ftn abort case, one toolchain at a time (fixed build directories).
#   flux batch -q pbatch -N1 -t 30 --output=logs/tuo.cif.ENV.log run_cif.sh ENV
ulimit -c 0
cd <site>/compliant/vendor/checks || exit 1
timeout --kill-after=30 1700 python3 -I run_checks.py run --machine tuolumne --env $1 \
  --toolchains afar,cce19,cce20,cce21,cce21_4 --modes 1 --workers 1 --compiles 1 \
  --resume --cases cce-ftn-cif-record-split-abort --out results/tuolumne.$1.jsonl
rm -rf /tmp/cce-cif
