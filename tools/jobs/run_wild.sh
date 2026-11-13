#!/bin/bash
# The in-the-wild cases (data/bench/wild/) on Tuolumne toolchains in
# both memory modes (results/wild/runs/<toolchain>.<mode>.jsonl; resumable).
# Submit: flux batch -q pbatch -N1 -t 60 --setattr=thp=always \
#   --output=results/wild/run.%j.log tools/jobs/run_wild.sh afar cce19
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
echo "host $(hostname) git $(git rev-parse --short HEAD) start $(date -Is) toolchains $*"
T=/tmp/${USER:-user}-t34-$$
mkdir -p $T
export TMPDIR=$T
python3 -I tools/wild/wild_bench.py run --toolchains "$@" --jobs ${JOBS:-8}
echo "exit $? at $(date -Is)"
rm -rf $T
