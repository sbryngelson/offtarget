#!/bin/bash
# GCC's full catalog run, separate memory (row key 0): Fortran and C OpenMP
# 5.0/5.2/6.0, Fortran and C OpenACC 3.4, through tools/campaigns/run_matrix.py run
# (resumable: a rerun of this script continues), the canaries with the
# first queue. Each argument is one GPU's queue, "tag[+tag...]" of f90, c,
# acc, accc; every queue runs on its own GPU, all bounded by LIMIT_S.
#   wingtip (TC=gcc_sm80): FREE GPUs only (none of another process), inside
#     the cap, nice, the per-GPU run lock, WORKERS compiles per queue (the
#     total at most 4):
#       TC=gcc_sm80 WORKERS=2 setsid nohup tools/jobs/run_gcc_full.sh f90 c+acc+accc &
#   Tioga (TC=gcc_g90): inside ONE foreground interactive pdebug job of at
#     most 60 minutes (one GCD per queue, ROCR_VISIBLE_DEVICES):
#       flux run -q pdebug -N1 -n1 -t 60m --job-name=compile-test-gcc-catalog \
#         env TC=gcc_g90 WORKERS=8 LIMIT_S=3300 tools/jobs/run_gcc_full.sh f90 c acc+accc
# Rows: results/gcc/$TC/matrix.<tag>.x0.jsonl (+ .meta.json, .log).
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
set -u
cd "$(dirname "$0")/../.."
ulimit -c 0
. tools/jobs/toolchains.sh  # generated from catalog/toolchains.yaml: the lanes' toolchains
TC=${TC:?TC=one of $TC_LANE_gcc}
tc_check "$TC" gcc || exit 2
ON_WINGTIP=$([ "$(tc_machine "$TC")" = wingtip ] && echo 1 || true)
PY=${PY:-python3}
WORKERS=${WORKERS:-2}
LIMIT_S=${LIMIT_S:-7200}
R=results/gcc/$TC; mkdir -p "$R"
END=$(( $(date +%s) + LIMIT_S ))
if [ -n "$ON_WINGTIP" ]; then
  [ $(( WORKERS * $# )) -le 4 ] || { echo "at most 4 compiles on wingtip"; exit 2; }
  busy=$(nvidia-smi --query-compute-apps=gpu_uuid --format=csv,noheader | tr -d ' ')
  mapfile -t free < <(nvidia-smi --query-gpu=index,uuid,memory.used --format=csv,noheader,nounits |
    tr -d ' ' | awk -F, -v b="$busy" 'index(b, $2) == 0 && $3 < 100 {print $1}')
  [ "${#free[@]}" -ge "$#" ] || { echo "$# queues, free GPUs: ${free[*]:-none}: refused"; exit 3; }
  NICE="nice -n 10"
else
  free=(0 1 2 3 4 5 6 7)
  NICE=""
fi
echo "host $(hostname) $(date -Is) TC=$TC queues $* workers $WORKERS rev $(git rev-parse --short HEAD 2>/dev/null || cat .wingtip_rev 2>/dev/null)"
run_one() {  # tag canaries(yes|no)
  local tag=$1 A left out
  case "$tag" in
    f90) A="--versions 50 52 60" ;;
    c) A="--lang c --versions 50 52 60" ;;
    acc) A="--versions 34" ;;
    accc) A="--lang c --versions 34" ;;
    *) echo "bad tag $tag"; return 2 ;;
  esac
  left=$(( END - $(date +%s) ))
  [ "$left" -gt 60 ] || { echo "no time left for $tag"; return 1; }
  out=$R/matrix.$tag.x0.jsonl
  local can=(--canaries-exempt "the canaries run with the campaign's first queue")
  [ "$2" = yes ] && can=()
  echo "[$(date -Is)] GPU $GPU: $tag, $left s left"
  $NICE timeout --kill-after=30 "$left" $PY -I tools/campaigns/run_matrix.py run --xnack 0 \
    --toolchains "$TC" $A --workers "$WORKERS" --out "$out" --resume "${can[@]}" \
    > "$R/matrix.$tag.x0.log" 2>&1
  local rc=$?
  echo "[$(date -Is)] GPU $GPU: $tag exit $rc rows $(wc -l < "$out")"
}
i=0
for q in "$@"; do
  (
    GPU=${free[$i]}
    if [ -n "$ON_WINGTIP" ]; then
      export CUDA_VISIBLE_DEVICES=$GPU COMPLIANT_RUN_SLOTS=1
    else
      export ROCR_VISIBLE_DEVICES=$GPU
    fi
    IFS=+ read -ra tags <<< "$q"
    for t in "${tags[@]}"; do
      run_one "$t" "$([ "$i" = 0 ] && [ "$t" = "${tags[0]}" ] && echo yes || echo no)"
    done
  ) &
  i=$((i + 1))
done
wait
echo "done $(date -Is)"
