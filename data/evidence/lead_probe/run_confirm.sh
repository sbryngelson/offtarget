#!/bin/bash
# The two promoted findings in the gate's environments (see
# confirm_jobs.py). flux run -N1 -q pdebug --job-name=compile-test-run-confirm -t 20m data/evidence/lead_probe/run_confirm.sh MACHINE
ulimit -c 0
M=$1
cd "${T47_ROOT:-$PWD}" || exit 1
export T48_TMP=/tmp/${USER}_t47_confirm
rm -rf "$T48_TMP"; mkdir -p "$T48_TMP" results/t47
${PY:-python3} -I data/evidence/lead_probe/confirm_jobs.py "$M" > "results/t47/confirm_$M.jobs.jsonl"
echo "node $(hostname) $(date -Is)"
timeout --kill-after=10 900 ${PY:-python3} -I data/evidence/gate_probe/probe.py \
  "results/t47/confirm_$M.jobs.jsonl" "results/t47/confirm_$M.jsonl" --workers ${WORKERS:-4}
rm -rf "$T48_TMP"
