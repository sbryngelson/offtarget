#!/bin/bash
# `confirm batch --run` over many programs, as shards in
# parallel on one compute node. Each shard (one process) writes its cases
# to results/confirm/shards/$TAG.batch.K.jsonl and the evidence it ran to
# results/confirm/shards/$TAG.ev.K.jsonl (reading the main store too);
# merge the evidence stores into results/confirm/evidence.jsonl
# afterwards. A shard cut by the time limit is resumed by submitting the
# same shards again (its runs are in its evidence store).
#   SOURCES  programs.jsonl files (space separated)
#   N        number of shards, K0..K1 the shards this node runs (or KS:
#            a list of shard numbers)
#   OUTCOMES outcome classes (default: run-time failures)
#   TAG      name of the shard files
#   RUN      --run (default) or "" for an offline batch (stored evidence)
#   READ     more evidence stores to read (globs, e.g. the stores of an
#            earlier shard numbering: "results/confirm/shards/s1run.ev.*")
# Submit:
#   flux batch -q pbatch -N1 -t 60 --setattr=thp=always \
#     --env=SOURCES="results/fuzz/s1-00/programs.jsonl ..." --env=N=48 \
#     --env=K0=0 --env=K1=11 --env=TAG=s1run \
#     --output=results/confirm/shards/s1run.0-11.log tools/jobs/run_confirm_shards.sh
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "git $(git rev-parse --short HEAD) thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
OUTCOMES=${OUTCOMES:-"crash run_error wrong_answer fell_back_to_host"}
mkdir -p results/confirm/shards
for k in ${KS:-$(seq $K0 $K1)}; do
  (
    T=/tmp/${USER:-user}-shard-${FLUX_JOB_ID:-none}-$k
    mkdir -p $T
    export TMPDIR=$T
    python3 -I tools/confirm.py batch --from $SOURCES ${RUN---run} \
      --outcomes $OUTCOMES --shard $k/$N \
      --store results/confirm/shards/$TAG.ev.$k.jsonl \
      --read ${READ:-} \
      --out results/confirm/shards/$TAG.batch.$k.jsonl \
      > results/confirm/shards/$TAG.shard.$k.log 2>&1
    echo "shard $k exit $? at $(date -Is)"
    rm -rf $T
  ) &
done
wait
echo "done $(date -Is)"
