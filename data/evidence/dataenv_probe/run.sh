#!/bin/bash
# Probes: each file on each toolchain and memory mode through the
# confirmer (its own cell run, the other toolchains, the elision), JSON
# results in results/t28_probe/<file>.<toolchain>.<mode>.json.
# Submit: flux batch -q pbatch -N1 -t 60 --setattr=thp=always \
#   --env=FILES="lpcond_simd_down.f90 ..." \
#   --output=results/t28_probe/run.log data/evidence/dataenv_probe/run.sh
ulimit -c 0
cd <site>/compliant
mkdir -p results/t28_probe results/t28_probe/rt
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
T=/tmp/<user>-t28p-${FLUX_JOB_ID:-none}-$$
mkdir -p $T
export TMPDIR=$T
for f in $FILES; do
  for tc in ${TOOLCHAINS:-afar cce19 cce20 cce21}; do
    for m in ${MODES:-unified copy}; do
      python3 -I tools/confirm.py case data/evidence/dataenv_probe/$f --toolchain $tc \
        --mode $m --run > results/t28_probe/$f.$tc.$m.json 2> results/t28_probe/$f.$tc.$m.err &
    done
  done
  wait
done
rm -rf $T
echo "done $(date -Is)"
