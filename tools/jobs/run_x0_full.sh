#!/bin/bash
# Copy mode (HSA_XNACK=0) for the WHOLE catalog, one language and
# one toolchain per flux job (THP=always). Each job writes its own raw
# files under results/task26/ (never the full result files); afterwards
#   python3 -I tools/campaigns/run_matrix.py replace --out <work copy of the full
#     file> --inputs results/task26/<raw files>
# replaces the HSA_XNACK=0 rows in place (every other row is kept; the
# command refuses to shrink the file), and the checked work copy goes over
# the full file (keep a backup until the counts are checked).
# Env: LANG_ (f90 | c | acc), TC (afar | cce19 | cce20 | cce21),
# (OpenACC: TC="cce19 cce20 cce21", files tagged cce19-cce20-cce21),
# WORKERS (default 16), RESUME=--resume continues a run cut short,
# SKIP_BASELINE=1 skips the omp_vv baseline (OpenACC never has one).
# Submit (pdebug, at most 60 minutes):
#   flux batch -q pbatch -N1 -t 60 --setattr=thp=always \
#     --env=LANG_=f90 --env=TC=afar --output=results/task26/f90.afar.log \
#     tools/jobs/run_x0_full.sh
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
R=results/task26; mkdir -p $R
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
B=$(ls -A /var/tmp/${USER:-user} 2>&1 | sort)
T=/tmp/${USER:-user}-t26-${FLUX_JOB_ID:-$$}
mkdir -p $T
export TMPDIR=$T
case "$LANG_" in
  f90) A="--versions 50 52 60" ;;
  c) A="--lang c --versions ${VERSIONS:-50 52 60}" ;;  # C 5.0
  acc) A="--versions 34"; SKIP_BASELINE=1 ;;
  *) echo "LANG_ must be f90, c or acc"; exit 2 ;;
esac
. tools/jobs/toolchains.sh  # generated from catalog/toolchains.yaml: the lanes' toolchains
for t in $TC; do tc_check "$t" tuolumne || exit 2; done
TAG=${TC// /-}
BL=""
[ -z "$SKIP_BASELINE" ] && BL="--baseline-out $R/baseline.$LANG_.$TAG.x0.jsonl"
python3 -I tools/campaigns/run_matrix.py run --xnack 0 --toolchains $TC $A \
  --workers ${WORKERS:-16} --out $R/matrix.$LANG_.$TAG.x0.jsonl $BL $RESUME
echo "exit $? at $(date -Is)"
echo "leftover in own TMPDIR:"; ls -A $T
rm -rf $T
echo "var/tmp diff (before vs after):"
diff <(echo "$B") <(ls -A /var/tmp/${USER:-user} 2>&1 | sort)
echo done
