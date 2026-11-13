#!/bin/bash
# The vendor-packet checks on one Tuolumne compute node, one environment.
#   flux batch -q pbatch -N1 -t 60 --setattr=thp=always --output=logs/tuo.ENV.%j.log run_tuolumne.sh ENV [CASES]
# ENV a, b, d (c: the same as a, submitted as its own job so it runs on another node).
ulimit -c 0
cd <site>/compliant/vendor/checks || exit 1
E=$1; C=${2:+--cases $2}
unset ROCR_VISIBLE_DEVICES
echo "host $(hostname) env $E start $(date -Is)"
timeout --kill-after=30 3400 python3 -I run_checks.py run --machine tuolumne --env $E \
  --toolchains afar,cce19,cce20,cce21,cce21_4 --modes 1,0 --workers 40 --compiles 40 \
  --limit-s 3000 --resume $C --out results/tuolumne.$E.jsonl
python3 -I run_checks.py versions --machine tuolumne --toolchains afar,cce19,cce20,cce21,cce21_4 \
  --out results/versions.jsonl > /dev/null
rm -rf /tmp/${USER}-t44
echo "done $(date -Is)"
