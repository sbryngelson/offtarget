#!/bin/bash
# The reproduction gate's reruns on wingtip (NVHPC; one host, no
# scheduler). Runs inside the capped slice (tools/jobs/wingtip_cap.sh), nice,
# with the per-GPU run lock (COMPLIANT_RUN_SLOTS=1: one program per GPU).
# Two FREE GPUs: each takes one half of the planned rows in environments
# (a), (b) and (d), then the other half's environment (c), so (c) always
# runs on the other GPU (wingtip's "another node"). WORKERS per GPU (at
# most 2: 4 compiles across all agents).
#   ssh wingtip 'cd ~/compliant-t45 && nohup tools/jobs/run_wingtip_gate.sh \
#     LIMIT_S WORKERS CAMPAIGN... > results/gate/logs/wingtip.log 2>&1 &'
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
ulimit -c 0
cd "$(dirname "$0")/../.." || exit 1
LIM=$1; W=$2; shift 2
[ "$W" -le 2 ] || { echo "at most 2 workers per GPU"; exit 2; }
PY=${PY:-$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.confirm.machines import load; print(load()["wingtip"].access["python"])')}
mkdir -p results/gate/logs
# the free GPUs: no memory in use and no process
mapfile -t FREE < <(nvidia-smi --query-gpu=index,memory.used \
  --format=csv,noheader,nounits | awk -F', ' '$2 < 100 {print $1}')
echo "start $(date -Is) on $(hostname); free GPUs: ${FREE[*]}"
[ "${#FREE[@]}" -ge 2 ] || { echo "fewer than two free GPUs: stop"; exit 3; }
END=$(( $(date +%s) + LIM ))
export COMPLIANT_RUN_SLOTS=1
# phase P on GPU G: "abd K" runs shard K in (a), (b), (d); "c K" runs
# shard K in (c). One host: (c) of a row runs only after both (a,b,d)
# halves have finished, on the other GPU, in (a)'s path
phase() {
  local E=$1 K=$2 G=$3 C REM
  export CUDA_VISIBLE_DEVICES=$G
  export GATE_TMP=/tmp/${USER}_gate_wt
  mkdir -p "$GATE_TMP"
  for C in "${CAMPS[@]}"; do
    REM=$((END - $(date +%s)))
    [ "$REM" -gt 60 ] || break
    B=$(echo "$BUDGETS" | tr ' ' '\n' | grep "^$C=" | cut -d= -f2)
    nice -n 10 timeout --kill-after=10 $((REM + 1800)) "$PY" -I \
      tools/campaigns/gate.py run --campaign "$C" --machine wingtip --envs "$E" \
      --shard "$K/2" --workers "$W" --limit-s "$REM" --gpus 1 \
      --concurrent 2 ${B:+--budget-gpu-h $B}
  done
}
CAMPS=("$@")
phase a,b,d 0 "${FREE[0]}" > results/gate/logs/wingtip.abd0.log 2>&1 &
phase a,b,d 1 "${FREE[1]}" > results/gate/logs/wingtip.abd1.log 2>&1 &
wait
phase c 1 "${FREE[0]}" > results/gate/logs/wingtip.c1.log 2>&1 &
phase c 0 "${FREE[1]}" > results/gate/logs/wingtip.c0.log 2>&1 &
wait
rm -rf /tmp/${USER}_gate_wt
rmdir /tmp/${USER}_gate_wt_* 2>/dev/null
echo "all done $(date -Is)"
