#!/bin/bash
# Direct runs on wingtip (NVIDIA A100 x4, NVHPC 25.11; no scheduler,
# a shared login node). Each argument is one GPU's queue of runs, run in
# order: "<kind>:<lang>:<mode>[+<kind>:<lang>:<mode>...]", kind matrix
# (the catalog: f90 = OpenMP 5.0/5.2/6.0, c = OpenMP C 5.2/6.0, acc =
# OpenACC 3.4), baseline (omp_vv: lang f90 | c; acc_vv: lang accvv), audit
# (tools/campaigns/oracle_audit.py: f90 | c | acc), expected (tools/derive/expected.py
# catalog; lang ignored, write "cat") or fuzz (the fixed fuzz sample of
# confirm regress, seeds 1-200; lang ignored), mode
# a row key of catalog/machines.yaml wingtip (0 = separate, 2 = managed).
# Rules of the machine (task-33 brief): only GPUs with no other user's
# process (nvidia-smi --query-compute-apps), at most one program per GPU at
# a time (CUDA_VISIBLE_DEVICES + COMPLIANT_RUN_SLOTS=1: compiles stay
# parallel, runs are serialised), nice -n 10, at most 16 compiles at once
# (WORKERS per queue, default 4, times the queues; keep the total of all
# running drivers <= 16). GPUS="2 3" picks the GPUs (one queue each; a GPU
# our own other driver uses would then run two programs at once: only for
# drivers that do not overlap in time). Runs are resumable
# (--resume: RESUME=1). TC=nvhpc269 runs NVHPC 26.9 (default nvhpc, 25.11). Raw files: results/$TC/raw/<kind>.<lang>.x<mode>.jsonl
# (+ .meta.json, .log). Start detached, e.g.
#   nohup tools/jobs/run_wingtip.sh matrix:f90:0 matrix:f90:2 > results/nvhpc/raw/q.log 2>&1 &
. "$(dirname "$0")/wingtip_cap.sh" || exit 1  # all wingtip work runs in the capped compliant.slice
set -u
cd "$(dirname "$0")/../.."
ulimit -c 0
PY=${PY:-$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.confirm.machines import load; print(load()["wingtip"].access["python"])')}
. tools/jobs/toolchains.sh  # generated from catalog/toolchains.yaml: the lanes' toolchains
TC=${TC:-${TC_LANE_wingtip%% *}}  # the NVHPC release (the wingtip lane's first by default)
tc_check "$TC" wingtip || exit 2
R=results/$TC/raw; mkdir -p $R
WORKERS=${WORKERS:-4}
if [ $(( WORKERS * $# )) -gt 16 ]; then echo "WORKERS x queues > 16 compiles"; exit 2; fi
# free GPUs: no compute process of another user on them (our own runs
# may share a GPU only through GPUS=, one queue per GPU still)
busy=""
while IFS=, read -r uuid pid; do
  owner=$(ps -o user= -p "${pid// /}" 2>/dev/null)
  if [ "$owner" != "$(id -un)" ]; then busy="$busy ${uuid// /}"; fi
done < <(nvidia-smi --query-compute-apps=gpu_uuid,pid --format=csv,noheader)
free=()
while IFS=, read -r idx uuid; do
  uuid=${uuid// /}
  if ! grep -q "$uuid" <<< "$busy"; then free+=("$idx"); fi
done < <(nvidia-smi --query-gpu=index,uuid --format=csv,noheader)
if [ -n "${GPUS:-}" ]; then  # chosen GPUs, each must be free of others
  want=($GPUS)
  for g in "${want[@]}"; do
    if ! printf '%s\n' "${free[@]}" | grep -qx "$g"; then
      echo "GPU $g has another user's process: refused"; exit 2
    fi
  done
  free=("${want[@]}")
fi
if [ "${#free[@]}" -lt "$#" ]; then
  echo "$# queues, free GPUs: ${free[*]:-none}: refused"; exit 2
fi
echo "host $(hostname) start $(date -Is) rev $(cat .wingtip_rev 2>/dev/null) free GPUs ${free[*]}"
run_one() {  # kind lang mode
  local kind=$1 L=$2 X=$3 A out bl=""
  case "$L" in
    f90) A="--versions 50 52 60" ;;
    c) A="--lang c --versions ${VERSIONS:-50 52 60}" ;;  # C 5.0
    acc) A="--versions 34" ;;
    accc) A="--lang c --versions 34" ;;  # OpenACC C
    accvv) A="--repos acc_vv --versions 34" ;;
    cat|x) A="" ;;  # expected and fuzz: no language
    *) echo "bad lang $L"; return 2 ;;
  esac
  out=$R/$kind.$L.x$X.jsonl
  echo "[$(date -Is)] GPU $CUDA_VISIBLE_DEVICES: $kind $L x$X"
  case "$kind" in
    matrix|baseline)
      if [ "$kind" = baseline ]; then
        bl="--skip-matrix --baseline-out $out"; out=$R/$kind.$L.x$X.matrix-unused.jsonl
      fi
      nice -n 10 $PY -I tools/campaigns/run_matrix.py run --xnack $X --toolchains $TC $A \
        --workers $WORKERS --out $out $bl ${RESUME:+--resume} > $R/$kind.$L.x$X.log 2>&1 ;;
    audit)  # the oracle (mutation) audit, partial outputs next to the JSONL
      case "$L" in f90) M="" ;; c) M="--lang c" ;; acc) M="--model acc" ;;
        accc) M="--model acc --lang c" ;; esac 
      # AUDIT_VERSIONS="50" audits some versions only (a partial run)
      nice -n 10 $PY -I tools/campaigns/oracle_audit.py $M --toolchains $TC --xnack $X \
        ${AUDIT_VERSIONS:+--versions $AUDIT_VERSIONS} \
        --workers $WORKERS --out $out --md $R/$kind.$L.x$X.md \
        --summary $R/$kind.$L.x$X.summary.json > $R/$kind.$L.x$X.log 2>&1 ;;
    expected)  # the expected-behaviour catalog set (needs results/matrix.jsonl)
      nice -n 10 $PY -I tools/derive/expected.py catalog --toolchains $TC --xnack $X \
        --workers $WORKERS --out $R/expected.catalog.$TC.jsonl > $R/$kind.$L.x$X.log 2>&1 ;;
    fuzz)  # the fixed fuzz sample of confirm regress (FUZZ_SAMPLE) on nvhpc
      nice -n 10 $PY -I -c "
import sys; sys.path.insert(0, '.')
from pathlib import Path
from offload.engine import fuzz_exec as fe
from offload.engine.confirm.regress import FUZZ_SAMPLE as F
a, b = F['seeds']
fe.campaign(Path('$R/fuzz.x$X'), range(a, b + 1), $WORKERS, ('$TC',),
            gen_version=F['gen_version'], base=F['base'], xnack=$X)
" > $R/$kind.$L.x$X.log 2>&1 ;;
    *) echo "bad kind $kind"; return 2 ;;
  esac
  echo "[$(date -Is)] GPU $CUDA_VISIBLE_DEVICES: $kind $L x$X exit $?"
}
i=0
for q in "$@"; do
  (
    export CUDA_VISIBLE_DEVICES=${free[$i]} COMPLIANT_RUN_SLOTS=1
    IFS=+ read -ra items <<< "$q"
    for it in "${items[@]}"; do
      IFS=: read -r kind L X <<< "$it"
      run_one "$kind" "$L" "$X"
    done
  ) &
  i=$((i + 1))
done
wait
echo "all done $(date -Is)"
