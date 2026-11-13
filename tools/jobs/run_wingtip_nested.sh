#!/bin/bash
# nested-data: the programs on wingtip (NVHPC 25.11 and 26.9, separate and
# managed memory; GCC 16.2 sm_80, separate memory), from a private copy of the
# tree (tools/jobs/nested_remote.sh push wingtip copies the tree and the stored pre-run in). Inside the capped slice
# (tools/jobs/wingtip_cap.sh), nice, with the per-GPU run lock
# (COMPLIANT_RUN_SLOTS=1), on two FREE GPUs, at most 2 workers per GPU (4
# compiles). Each GPU runs half of the cells; then the gate: half K's failing
# rows in (a), (b), (d) on GPU K and the other half's (c) on GPU K.
#   ssh HOST 'cd <campaign_lanes>/nested-lane && setsid nohup \
#     tools/jobs/run_wingtip_nested.sh LIMIT_S 2 main > results/nested/logs/wingtip.log 2>&1 < /dev/null &'
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
ulimit -c 0
cd "$(dirname "$0")/../.." || exit 1
LIM=$1; W=$2; NAME=$3; PHASES=${4:-"run gate"}
[ "$W" -le 2 ] || { echo "at most 2 workers per GPU"; exit 2; }
PY=${PY:-$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.confirm.machines import load; print(load()["wingtip"].access["python"])')}
mkdir -p results/nested/logs
# WAIT_S: how long to wait (polling every 120 s) for two free GPUs
WAIT_S=${WAIT_S:-0}
WAIT_END=$(( $(date +%s) + WAIT_S ))
while :; do
  mapfile -t FREE < <(nvidia-smi --query-gpu=index,memory.used \
    --format=csv,noheader,nounits | awk -F', ' '$2 < 100 {print $1}')
  [ "${#FREE[@]}" -ge 2 ] && break
  [ "$(date +%s)" -lt "$WAIT_END" ] || { echo "fewer than two free GPUs: stop"; exit 3; }
  sleep 120
done
echo "start $(date -Is) on $(hostname); free GPUs: ${FREE[*]}"
T0=$(date +%s)
END=$(( T0 + LIM ))   # the run's own limit starts when the GPUs are free
export COMPLIANT_RUN_SLOTS=1
step() {   # step S (run|gate) of half K on GPU G
  local S=$1 K=$2 G=$3 REM
  export CUDA_VISIBLE_DEVICES=$G
  export TMPDIR=/tmp/${USER}_nested_wt_$K GATE_TMP=/tmp/${USER}_nestedgate_wt_$K
  mkdir -p "$TMPDIR" "$GATE_TMP"
  REM=$((END - $(date +%s)))
  if [ "$REM" -gt 60 ]; then
    if [ "$S" = run ]; then
      nice -n 10 timeout --kill-after=10 $((REM + 120)) "$PY" -I tools/campaigns/nested.py run \
        --name "$NAME" --machine wingtip --workers "$W" --shard "$K/2" --limit-s "$REM"
    else
      # (a), (b), (d) of this half here; (c) of the other half here, so
      # (c), "another node", is another GPU of the host
      nice -n 10 timeout --kill-after=10 $((REM + 120)) "$PY" -I tools/campaigns/nested.py gate \
        --name "$NAME" --machine wingtip --shard "$K/2" --envs a,b,d --workers "$W"
      REM=$((END - $(date +%s)))
      [ "$REM" -gt 60 ] && nice -n 10 timeout --kill-after=10 $((REM + 120)) "$PY" -I \
        tools/campaigns/nested.py gate --name "$NAME" --machine wingtip --shard "$((1 - K))/2" \
        --envs c --workers "$W"
    fi
  fi
  rm -rf "$TMPDIR" "$GATE_TMP"
}
for S in $PHASES; do
  step "$S" 0 "${FREE[0]}" > results/nested/logs/wingtip.$S.0.log 2>&1 &
  step "$S" 1 "${FREE[1]}" > results/nested/logs/wingtip.$S.1.log 2>&1 &
  wait
done
T1=$(date +%s)
echo "{\"machine\": \"wingtip\", \"gpus\": 2, \"phases\": \"$PHASES\", \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(2*($T1-$T0)/3600, 3))")}" >> results/nested/ledger.jsonl
echo "all done $(date -Is)"
