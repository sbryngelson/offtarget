#!/bin/bash
# HSA_XNACK=1 configuration (matrix + omp_vv baseline), run once
# inside one flux allocation with THP=always. Non-strict on purpose. Submit:
#   flux alloc --setattr=thp=always -N1 -q pdebug --job-name=compile-test-run-matrix-xnack1 -t 60 \
#     tools/jobs/run_matrix_xnack1.sh > results/task10/xnack1.log 2>&1
# NOTE=thp=unavailable runs without THP and marks every row's flags;
# RESUME=--resume continues a run cut short.
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
R=results/task10; mkdir -p $R
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
echo "var/tmp before:"; ls -A /var/tmp/${USER:-user} 2>&1 | sort > $R/xnack1.vartmp.before; wc -l < $R/xnack1.vartmp.before
T=/tmp/${USER:-user}-task10-${FLUX_JOB_ID:-x}
mkdir -p $T
export TMPDIR=$T
NOTE="${NOTE:-}"
python3 -I tools/campaigns/run_matrix.py run --xnack 1 --workers ${WORKERS:-16} \
  --out results/matrix.xnack1.jsonl --baseline-out results/baseline.xnack1.jsonl \
  ${NOTE:+--flags-note $NOTE} $RESUME
echo "exit $? at $(date -Is)"
echo "leftover in own TMPDIR:"; ls -A $T
rm -rf $T
ls -A /var/tmp/${USER:-user} 2>&1 | sort > $R/xnack1.vartmp.after
echo "var/tmp diff (before vs after):"; diff $R/xnack1.vartmp.before $R/xnack1.vartmp.after
find "${COMPLIANT_ROOT:-$PWD}" -maxdepth 2 -name 'core*' -newer $R/xnack1.vartmp.before 2>/dev/null
echo done
