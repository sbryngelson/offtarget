#!/bin/bash
# The confirmer's offline
# batches (stored evidence only, no runs) on one compute node (docs/tooling/regenerate.md, step 7):
#  1. the full batch (catalog, omp_vv, OpenACC, fuzz b1-b5 and c1) in
#     $N shards -> results/confirm/shards/$TAG.full.K.jsonl;
#  2. the s1 batch (s1, s1x0 and the fuzz-4 reruns, reading the run shards'
#     evidence stores) in $N shards -> results/confirm/shards/$TAG.s1.K.jsonl;
#  3. the shards concatenated in shard order: $TAG.full.jsonl, $TAG.s1.jsonl;
#  4. with INSTALL=1: the previous batch_full.jsonl / batch_s1.jsonl kept as
#     *.pre-$TAG.jsonl, the new ones installed, and `confirm decide`
#     (catalog/triage_28.yaml) -> batch_s1.final.jsonl.
# The full batch is exactly this with N=8 (shards
# full6.batch.0-7, s1off6.batch.0-7).
# Submit (pdebug, about 5 minutes):
#   flux batch -q pbatch -N1 -t 30 --setattr=thp=always --env=INSTALL=1 \
#     --output=results/confirm/shards/regen.log tools/jobs/run_regen_confirm.sh
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}" || exit 1
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "git $(git rev-parse --short HEAD)"
N=${N:-8}
TAG=${TAG:-regen}
D=results/confirm/shards
T=/tmp/${USER:-user}-regen-${FLUX_JOB_ID:-none}-$$
mkdir -p $T $D
export TMPDIR=$T
ALL="rejected ice timeout harness_error accepted_ignored crash run_error wrong_answer fell_back_to_host"
# The fuzz-4s50 samples (AMD and NVHPC), once joined
T37=$(for c in n0x0 n1x0; do [ -f results/fuzz/$c/programs.jsonl ] && echo results/fuzz/$c/programs.jsonl; done)
FULL="results/matrix.jsonl results/matrix_c.jsonl results/acc_matrix.jsonl results/acc_matrix_c.jsonl results/baseline.jsonl results/baseline_c.jsonl results/fuzz/c1/programs.jsonl results/fuzz/b1/programs.jsonl results/fuzz/b2/programs.jsonl results/fuzz/b3/programs.jsonl results/fuzz/b4/programs.jsonl results/fuzz/b5/programs.jsonl $T37"
G4="results/fuzz/s1g4/programs.jsonl results/fuzz/s1g4x0/programs.jsonl results/fuzz/b5g4/programs.jsonl"
S1="results/fuzz/s1/programs.jsonl results/fuzz/s1x0/programs.jsonl $G4"
SH="results/confirm/shards/g4.ev.jsonl results/confirm/shards/s1run.ev.*.jsonl results/confirm/shards/s1run2.ev.*.jsonl results/confirm/shards/s1run4.ev.*.jsonl results/confirm/shards/s1run5.ev.*.jsonl"
for k in $(seq 0 $((N - 1))); do
  python3 -I tools/confirm.py batch --from $FULL --outcomes $ALL \
    --shard $k/$N --out $D/$TAG.full.$k.jsonl > $D/$TAG.full.$k.log 2>&1 &
  python3 -I tools/confirm.py batch --from $S1 --outcomes $ALL \
    --shard $k/$N --read $SH --out $D/$TAG.s1.$k.jsonl \
    > $D/$TAG.s1.$k.log 2>&1 &
done
wait
for k in $(seq 0 $((N - 1))); do
  tail -1 $D/$TAG.full.$k.log; tail -1 $D/$TAG.s1.$k.log
done
cat $(for k in $(seq 0 $((N - 1))); do echo $D/$TAG.full.$k.jsonl; done) > $D/$TAG.full.jsonl
cat $(for k in $(seq 0 $((N - 1))); do echo $D/$TAG.s1.$k.jsonl; done) > $D/$TAG.s1.jsonl
wc -l $D/$TAG.full.jsonl $D/$TAG.s1.jsonl
if [ -n "$INSTALL" ]; then
  C=results/confirm
  cp -p $C/batch_full.jsonl $C/batch_full.pre-$TAG.jsonl
  cp -p $C/batch_s1.jsonl $C/batch_s1.pre-$TAG.jsonl
  cp -p $C/batch_s1.final.jsonl $C/batch_s1.final.pre-$TAG.jsonl
  cp $D/$TAG.full.jsonl $C/batch_full.jsonl
  cp $D/$TAG.s1.jsonl $C/batch_s1.jsonl
  python3 -I tools/confirm.py decide --batch $C/batch_s1.jsonl \
    --out $C/batch_s1.final.jsonl
  python3 -I tools/regenerate.py --stamp-batch
  # Every verdict change of this rebuild
  python3 -I tools/derive/confirm_batch_changes.py --rebuild $TAG \
    --pair $C/batch_full.pre-$TAG.jsonl $C/batch_full.jsonl \
    --pair $C/batch_s1.final.pre-$TAG.jsonl $C/batch_s1.final.jsonl
  echo "installed at $(date -Is)"
fi
rm -rf $T
echo "done $(date -Is)"
