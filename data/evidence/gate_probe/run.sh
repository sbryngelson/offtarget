#!/bin/bash
# The probe jobs on one compute node (node-local build root).
#   flux batch -q pbatch -N1 -t 60 --output=results/t48/logs/%j.log \
#     data/evidence/gate_probe/run.sh JOBS OUT WORKERS LIMIT_S
ulimit -c 0
cd "${T48_ROOT:-$PWD}" || exit 1
JOB=$(flux getattr jobid 2>/dev/null || echo "p$$")
export T48_TMP=/tmp/${USER}_t48_${JOB}
mkdir -p "$T48_TMP"
unset ROCR_VISIBLE_DEVICES
echo "job $JOB on $(hostname) start $(date -Is)"
timeout --kill-after=10 "${4:-3000}" ${PY:-python3} -I data/evidence/gate_probe/probe.py "$1" "$2" --workers "${3:-12}"
echo "rc $? end $(date -Is)"
rm -rf "$T48_TMP"
