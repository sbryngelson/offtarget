#!/bin/bash
# A fuzz run of a list of seeds (the seeds a generator fix
# changes), all base groups, on a compute node.
#   flux batch -q pbatch -N1 -t 60 --setattr=thp=always \
#     --env=RUN_ID=s1g4 --env=SEEDS="10 372" --env=XNACK=1 \
#     --env=GEN=fuzz-4 --env=BASE="types derived alloc declare multitu" \
#     --output=results/fuzz/batch/s1g4.log tools/jobs/run_fuzz_seeds.sh
set -u
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
echo "host $(hostname) thp $(cat /sys/kernel/mm/transparent_hugepage/enabled) start $(date -Is)"
python3 -I tools/campaigns/fuzz.py run --run-id "$RUN_ID" --seeds $SEEDS --xnack "$XNACK" \
  --gen-version "$GEN" --workers ${WORKERS:-12} --base-features $BASE
echo "done $(date -Is) rc $?"
