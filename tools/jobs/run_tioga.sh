#!/bin/bash
# The whole in-scope catalog and the omp_vv baseline on Tioga
# (MI250X, gfx90a, a discrete GPU) at HSA_XNACK=0 only,
# one language and one compiler per flux job, run from the
# working copy on /p/vast1 (Tioga does not mount /p/lustre5). Each job
# writes its own raw files under results/tioga/ of that copy; copy them
# back into the main repository's results/tioga/ (git-ignored) and merge
# them into the full result files with `run_matrix.py replace` (new cells:
# the gfx90a toolchains are named <compiler>_g90, so no gfx942 row is
# touched).
# Env: LANG_ (f90 | c | acc), TC (afar | cce19 | cce20 | cce21; OpenACC:
# "cce19 cce20 cce21"), WORKERS (default 16), RESUME=--resume continues a
# run cut short, SKIP_BASELINE=1 skips the omp_vv baseline.
# Submit on Tioga (ssh tio; flux there; pdebug 12 h, pllm 1 d):
#   flux batch -q pllm -N1 -t 180 --env=LANG_=f90 --env=TC=afar \
#     --output=results/tioga/f90.afar.log tools/jobs/run_tioga.sh
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
PY=/usr/tce/bin/python3  # Tioga's /usr/bin/python3 is 3.6
R=results/tioga; mkdir -p $R
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "git $(git rev-parse --short HEAD)"
echo "thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
T=/tmp/${USER:-user}-t30-${FLUX_JOB_ID:-none}-$$
mkdir -p $T
export TMPDIR=$T
case "$LANG_" in
  f90) A="--versions 50 52 60" ;;
  c) A="--lang c --versions ${VERSIONS:-50 52 60}" ;;  # C 5.0
  acc) A="--versions 34"; SKIP_BASELINE=1 ;;
  *) echo "LANG_ must be f90, c or acc"; exit 2 ;;
esac
. tools/jobs/toolchains.sh  # generated from catalog/toolchains.yaml: the lanes' toolchains
TCS=""
for t in $TC; do tc_check "${t}_g90" tioga || exit 2; TCS="$TCS ${t}_g90"; done
TAG=${TC// /-}
BL=""
[ -z "$SKIP_BASELINE" ] && BL="--baseline-out $R/baseline.$LANG_.$TAG.g90.jsonl"
$PY -I tools/campaigns/run_matrix.py run --xnack 0 --toolchains $TCS $A \
  --workers ${WORKERS:-16} --out $R/matrix.$LANG_.$TAG.g90.jsonl $BL $RESUME
echo "exit $? at $(date -Is)"
echo "leftover in own TMPDIR:"; ls -A $T
rm -rf $T
echo done
