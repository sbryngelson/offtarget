#!/bin/bash
# Probes on a Tuolumne compute node:
#   flux batch -q pbatch -N1 -t 60 --setattr=thp=always \
#     --output=results/t27b/probes.log data/evidence/triage_probe/run.sh
ulimit -c 0
cd <site>/compliant
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is) git $(git rev-parse --short HEAD)"
echo "thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
python3 -I data/evidence/triage_probe/run.py "$@"
echo "exit $? at $(date -Is)"
