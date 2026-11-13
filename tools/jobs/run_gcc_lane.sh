#!/bin/bash
# GCC's bounded smoke run of the catalog (tools/campaigns/gcc_subset.py: N_F Fortran
# OpenMP, N_C C OpenMP, N_ACC Fortran OpenACC programs; legal, evenly spaced)
# through the harness in separate memory (row key 0), from a private copy
# of the tree, then (CANARIES=1) the canaries. Each step is bounded
# (LIMIT_S seconds in all, shared by the steps).
#   wingtip: TC=gcc_sm80 on one FREE GPU (none of another user's processes),
#     inside the cap, nice, the per-GPU run lock, WORKERS (default 4) compiles
#     tools/jobs/run_gcc_lane.sh   (detached: setsid nohup ... &)
#   Tioga: TC=gcc_g90 inside one bounded interactive flux run (a compiler
#     job's name), WORKERS 8, one GCD per run (ROCR_VISIBLE_DEVICES)
# Rows: results/gcc/$TC/subset.<f90|c|acc>.x0.jsonl (+ .meta.json, .log).
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
set -u
cd "$(dirname "$0")/../.."
ulimit -c 0
. tools/jobs/toolchains.sh  # generated from catalog/toolchains.yaml: the lanes' toolchains
TC=${TC:?TC=one of $TC_LANE_gcc}
tc_check "$TC" gcc || exit 2
PY=${PY:-python3}
WORKERS=${WORKERS:-4}
LIMIT_S=${LIMIT_S:-3000}
N_F=${N_F:-50} N_C=${N_C:-50} N_ACC=${N_ACC:-20}
R=results/gcc/$TC; mkdir -p "$R"
END=$(( $(date +%s) + LIMIT_S ))
if [ "$(tc_machine "$TC")" = wingtip ]; then
  [ "$WORKERS" -le 4 ] || { echo "at most 4 compiles on wingtip"; exit 2; }
  if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
    busy=$(nvidia-smi --query-compute-apps=gpu_uuid --format=csv,noheader | tr -d ' ')
    G=$(nvidia-smi --query-gpu=index,uuid,memory.used --format=csv,noheader,nounits |
        tr -d ' ' | awk -F, -v b="$busy" 'index(b, $2) == 0 && $3 < 100 {print $1; exit}')
    [ -n "$G" ] || { echo "no free GPU: refused"; exit 3; }
    export CUDA_VISIBLE_DEVICES=$G
  fi
  export COMPLIANT_RUN_SLOTS=1
  NICE="nice -n 10"
else
  NICE=""
fi
echo "host $(hostname) $(date -Is) TC=$TC gpu ${CUDA_VISIBLE_DEVICES:-${ROCR_VISIBLE_DEVICES:-all}} workers $WORKERS rev $(git rev-parse --short HEAD 2>/dev/null || cat .wingtip_rev 2>/dev/null)"
step() {  # lang versions n tag
  local L=$1 V=$2 n=$3 tag=$4 left
  left=$(( END - $(date +%s) ))
  [ "$left" -gt 60 ] || { echo "no time left for $tag"; return 1; }
  local ids
  ids=$($PY -I tools/campaigns/gcc_subset.py --lang "$L" --versions $V -n "$n") || return 1
  echo "[$(date -Is)] $tag: $(wc -w <<< "$ids") programs, $left s left"
  touch "$R/subset.$tag.x0.jsonl"  # rerun adds to an existing file
  $NICE timeout --kill-after=30 "$left" $PY -I tools/campaigns/run_matrix.py rerun \
    --xnack 0 --toolchains "$TC" --versions $V --lang "$L" \
    --programs $ids --workers "$WORKERS" --why "gcc smoke subset ($tag)" \
    --out "$R/subset.$tag.x0.jsonl" > "$R/subset.$tag.x0.log" 2>&1
  local rc=$?
  echo "[$(date -Is)] $tag exit $rc"
}
step f90 "50 52 60" "$N_F" f90
step c "50 52 60" "$N_C" c
step f90 34 "$N_ACC" acc
if [ -n "${CANARIES:-}" ]; then
  left=$(( END - $(date +%s) ))
  $NICE timeout --kill-after=30 "$left" $PY -I tools/campaigns/gate.py canaries \
    --toolchains "$TC" --xnack 0 --out "$R/canaries.x0.jsonl" > "$R/canaries.log" 2>&1
  rc=$?
  echo "[$(date -Is)] canaries exit $rc"
fi
echo "done $(date -Is)"
