#!/bin/bash
# Copy-mode subset in ONE flux allocation with THP=always: the subset
# programs (and the copy-semantics omp_vv tests) run at HSA_XNACK=1 and at
# HSA_XNACK=0 on the same node. Both reruns write into a work copy of the
# FULL results/matrix.jsonl and results/baseline.jsonl (rerun replaces only
# the subset's rows for that mode and keeps every other row), so the full
# files are never cut down to an intermediate. After checking the work copy,
# copy it over the full files. Non-strict on purpose.
# Submit:
#   WHY="..." flux alloc --setattr=thp=always -N1 -q pdebug --job-name=compile-test-run-copy-subset -t 60 \
#     tools/jobs/run_copy_subset.sh > results/copy_subset/copy_subset.log 2>&1
# Env: OUT, BOUT (work copies; default results/copy_subset/{matrix,baseline}
# .work.jsonl, created from the full files when absent), VERSIONS
# (default "50 52 60"), WORKERS (default 16).
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
mkdir -p results/copy_subset
OUT=${OUT:-results/copy_subset/matrix.work.jsonl}
BOUT=${BOUT:-results/copy_subset/baseline.work.jsonl}
[ -e "$OUT" ] || cp results/matrix.jsonl "$OUT"
[ -e "$BOUT" ] || cp results/baseline.jsonl "$BOUT"
VERSIONS=${VERSIONS:-50 52 60}
B=$(ls -A /var/tmp/${USER:-user} 2>&1 | sort)
T=/tmp/${USER:-user}-copy-$$
mkdir -p $T
export TMPDIR=$T
for X in 1 0; do
  python3 -I tools/campaigns/run_matrix.py rerun --xnack $X --copy-mode-subset \
    --versions $VERSIONS --workers ${WORKERS:-16} --out "$OUT" \
    --baseline-out "$BOUT" --why "${WHY:-copy-mode subset} (xnack=$X)"
  echo "xnack$X rerun exit $? at $(date -Is)"
done
tools/jobs/run_omp_vv_probes.sh
echo "probes exit $? at $(date -Is)"
echo "leftover in own TMPDIR:"; ls -A $T
rm -rf $T
echo "var/tmp diff (before vs after):"
diff <(echo "$B") <(ls -A /var/tmp/${USER:-user} 2>&1 | sort)
echo done
