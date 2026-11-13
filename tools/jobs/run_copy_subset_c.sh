#!/bin/bash
# The C copy-mode subset (run_matrix.copy_mode_subset(..., "c"):
# 89 programs and the copy-semantics omp_vv C tests) at HSA_XNACK=0 and the
# same programs again at HSA_XNACK=1 on AFAR and CCE 19 (the Fortran copy-mode
# toolchains), in ONE flux allocation with
# THP=always, so both modes share a node (the recipe of
# tools/jobs/run_copy_subset.sh). Rows of the other C programs in
# results/matrix_c.xnack1.jsonl / results/baseline_c.xnack1.jsonl are kept
# (rerun replaces only the subset's rows). Afterwards merge:
#   python3 -I tools/campaigns/run_matrix.py merge --lang c --copy-mode-subset \
#     --inputs results/matrix_c.xnack1.jsonl results/matrix_c.xnack0.jsonl \
#     --out results/matrix_c.jsonl --baseline-inputs \
#     results/baseline_c.xnack1.jsonl results/baseline_c.xnack0.jsonl \
#     --baseline-out results/baseline_c.jsonl
# Submit:
#   WHY="C copy-mode subset" flux alloc --setattr=thp=always -N1 \
#     -q pdebug -t 60 tools/jobs/run_copy_subset_c.sh \
#     > results/task20/copy_subset_c.log 2>&1
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
B=$(ls -A /var/tmp/${USER:-user} 2>&1 | sort)
T=/tmp/${USER:-user}-copy-c-$$
mkdir -p $T
export TMPDIR=$T
python3 -I tools/campaigns/run_matrix.py rerun --lang c --xnack 1 --copy-mode-subset \
  --toolchains afar cce19 \
  --workers ${WORKERS:-16} --out results/matrix_c.xnack1.jsonl \
  --baseline-out results/baseline_c.xnack1.jsonl --why "$WHY"
echo "xnack1 rerun exit $? at $(date -Is)"
python3 -I tools/campaigns/run_matrix.py run --lang c --xnack 0 --copy-mode-subset \
  --toolchains afar cce19 \
  --workers ${WORKERS:-16} --out results/matrix_c.xnack0.jsonl \
  --baseline-out results/baseline_c.xnack0.jsonl
echo "xnack0 subset exit $? at $(date -Is)"
echo "leftover in own TMPDIR:"; ls -A $T
rm -rf $T
echo "var/tmp diff (before vs after):"
diff <(echo "$B") <(ls -A /var/tmp/${USER:-user} 2>&1 | sort)
echo done
