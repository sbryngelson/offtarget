#!/bin/bash
# Regression-mode runs of a NEW toolchain (tools/confirm.py
# regress), one flux job per step. Every row goes to
# results/confirm/regress/<NEW>/ (never to the full result files):
#   JOB=matrix LANG_=f90|c|acc X=1|0   the whole catalog of the language
#       (and, for f90 and c, the omp_vv baseline) on NEW in one memory mode
#   JOB=fuzz   the fixed fuzz sample (FUZZ_START..FUZZ_START+FUZZ_COUNT-1,
#       generator fuzz-3, every base-language group, HSA_XNACK=1) on NEW
#       and LIKE side by side
#   JOB=confirm   tools/confirm.py regress confirm (repeats of both
#       toolchains on the differing cells, same node)
# Env: NEW (e.g. cce21_4), LIKE (e.g. cce21), WORKERS (default 16).
# Submit (pdebug, 60 minutes at most; tools/confirm.py regress plan prints
# the commands):
#   flux batch -q pbatch -N1 -t 60 --setattr=thp=always --env=JOB=matrix \
#     --env=LANG_=f90 --env=X=1 --env=NEW=cce21_4 \
#     --output=results/confirm/regress/cce21_4/matrix.f90.x1.log \
#     tools/jobs/run_regress.sh
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
R=results/confirm/regress/$NEW
mkdir -p $R
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "git $(git rev-parse --short HEAD) thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
T=/tmp/${USER:-user}-t31-${FLUX_JOB_ID:-none}-$$
mkdir -p $T
export TMPDIR=$T
case "$JOB" in
  matrix)
    case "$LANG_" in
      f90) A="--versions 50 52 60"; BL="--baseline-out $R/baseline.f90.x$X.jsonl" ;;
      c) A="--lang c --versions 50 52 60"; BL="--baseline-out $R/baseline.c.x$X.jsonl" ;;
      acc) A="--versions 34"; BL="" ;;
      *) echo "LANG_ must be f90, c or acc"; exit 2 ;;
    esac
    python3 -I tools/campaigns/run_matrix.py run --xnack $X --toolchains $NEW $A \
      --workers ${WORKERS:-16} --out $R/matrix.$LANG_.x$X.jsonl $BL $RESUME
    echo "matrix $LANG_ x$X exit $? at $(date -Is)" ;;
  fuzz)
    python3 -I tools/confirm.py regress fuzz --toolchain $NEW --like $LIKE \
      --workers ${WORKERS:-16}
    echo "fuzz exit $? at $(date -Is)" ;;
  confirm)
    python3 -I tools/confirm.py regress confirm --toolchain $NEW \
      --like $LIKE --workers ${WORKERS:-16}
    echo "confirm exit $? at $(date -Is)" ;;
  *) echo "JOB must be matrix, fuzz or confirm"; exit 2 ;;
esac
echo "leftover in own TMPDIR:"; ls -A $T
rm -rf $T
echo done
