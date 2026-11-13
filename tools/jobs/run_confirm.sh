#!/bin/bash
# Maintainers/confirm.py on a compute node (live runs need the GPU):
# CONFIRM_ARGS holds its arguments, e.g. "validate --live" or
# "regress confirm --toolchain cce21_4 --like cce21".
# Submit (pdebug, 60 minutes at most):
#   flux batch -q pbatch -N1 -t 60 --setattr=thp=always \
#     --env=CONFIRM_ARGS="validate --live" \
#     --output=results/confirm/validate_live.log tools/jobs/run_confirm.sh
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "git $(git rev-parse --short HEAD) thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
T=/tmp/${USER:-user}-t31c-${FLUX_JOB_ID:-none}-$$
mkdir -p $T
export TMPDIR=$T
eval "python3 -I tools/confirm.py $CONFIRM_ARGS"
echo "exit $? at $(date -Is)"
rm -rf $T
echo done
