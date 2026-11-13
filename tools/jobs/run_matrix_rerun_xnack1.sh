#!/bin/bash
# Run the programs whose source changed again under
# HSA_XNACK=1, inside one flux allocation with THP=always (other rows of
# results/matrix.xnack1.jsonl are kept). Non-strict on purpose. Submit:
#   PROGRAMS="id1 id2 ..." WHY="..." flux alloc --setattr=thp=always -N1 \
#     -q pdebug -t 30 tools/jobs/run_matrix_rerun_xnack1.sh \
#     > results/task10/rerun.xnack1.log 2>&1
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
B=$(ls -A /var/tmp/${USER:-user} 2>&1 | sort)
T=/tmp/${USER:-user}-rerun-$$
mkdir -p $T
export TMPDIR=$T
python3 -I tools/campaigns/run_matrix.py rerun --xnack 1 --workers ${WORKERS:-16} \
  --out results/matrix.xnack1.jsonl --programs $PROGRAMS --why "$WHY"
echo "exit $? at $(date -Is)"
echo "leftover in own TMPDIR:"; ls -A $T
rm -rf $T
echo "var/tmp diff (before vs after):"
diff <(echo "$B") <(ls -A /var/tmp/${USER:-user} 2>&1 | sort)
echo done
