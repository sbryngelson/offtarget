#!/bin/bash
# fortran-oop on Tuolumne as single foreground pdebug jobs (one node, <= 30 min, one
# at a time, named like compiler jobs: the maintainer's allowance for this campaign when
# pbatch was starved, 2026-10-28; batch work otherwise goes to pbatch). STEP: run | abd | c | fuzz-run K | fuzz-abd K | fuzz-c K. Resumable.
#   flux run -q pdebug -N1 -n1 --exclusive -t 30m --setattr=thp=always \
#     --job-name=compile-test-oop-N [--requires=host:H] tools/jobs/run_oop_pdebug.sh STEP [K]
ulimit -c 0
cd "$(dirname "$0")/../.." || exit 1
unset ROCR_VISIBLE_DEVICES
S=$1; K=${2:-0}; LIM=${LIMIT_S:-1500}
export TMPDIR=/tmp/${USER}_oop_pd GATE_TMP=/tmp/${USER}_oopgate_pd
mkdir -p "$TMPDIR" "$GATE_TMP" results/oop/logs
T0=$(date +%s)
echo "host $(hostname) step $S $K start $(date -Is) git $(git rev-parse --short HEAD)"
case $S in
  run) timeout -k 10 120 python3 -I tools/campaigns/oop.py prerun --name main --workers 8
       timeout -k 10 $((LIM + 60)) python3 -I tools/campaigns/oop.py run --name main --machine tuolumne \
         --workers 24 --limit-s "$LIM" ;;
  abd) timeout -k 10 $((LIM + 60)) python3 -I tools/campaigns/oop.py gate --name main --machine tuolumne \
         --envs a,b,d --node same --workers 8 ;;
  c) timeout -k 10 $((LIM + 60)) python3 -I tools/campaigns/oop.py gate --name main --machine tuolumne \
         --envs c --node other --workers 8 ;;
  fuzz-run) timeout -k 10 $((LIM + 60)) python3 -I tools/campaigns/fuzz.py run --run-id oop5-$K \
         --gen-version fuzz-5 --base-features derived oop --start $((1 + K * 150)) --count 150 \
         --workers 16 --xnack 1 --toolchains afar cce19 cce20 cce21 cce21_4 ;;
  fuzz-abd) timeout -k 10 $((LIM + 60)) python3 -I tools/campaigns/oop.py fuzz-gate --run oop5-$K \
         --envs a,b,d --node same --workers 8 ;;
  fuzz-c) timeout -k 10 $((LIM + 60)) python3 -I tools/campaigns/oop.py fuzz-gate --run oop5-$K \
         --envs c --node other --workers 8 ;;
esac
T1=$(date +%s)
echo "{\"job\": \"${FLUX_JOB_ID:-}\", \"machine\": \"tuolumne\", \"nodes\": 1, \"phases\": \"$S $K\", \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/oop/ledger.jsonl
rm -rf "$TMPDIR"
echo "done $(date -Is)"
