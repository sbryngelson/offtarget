#!/bin/bash
# The vendor-packet checks on wingtip (NVHPC 25.11 and 26.9, A100), inside the
# capped user slice (wingtip_cap.sh, docs/tooling/wingtip.md), nice, one program per GPU (the run
# lock in run_checks.py), at most 2 compiles. Start only when no other agent is compiling
# there (4 compiles across all agents).
#   setsid nohup ~/t44/checks/run_wingtip.sh ENV GPU [CASES|-] [VARIANTS] [VENDOR] \
#     > ~/t44/checks/logs/wt.ENV.log 2>&1 < /dev/null &
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
cd "$(dirname "$0")" || exit 1
ulimit -c 0
E=$1; G=$2; C=$3; V=${4:-repro,control}; VEN=${5:-}
used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "$G" | tr -d ' ')
[ "${used:-1}" -lt 100 ] || { echo "GPU $G is in use ($used MiB): not starting"; exit 1; }
echo "host $(hostname) env $E gpu $G start $(date -Is)"
args=()
[ -n "$C" ] && [ "$C" != "-" ] && args+=(--cases "$C")
[ -n "$VEN" ] && args+=(--vendor "$VEN")
timeout --kill-after=30 21600 nice -n 10 python3 -I run_checks.py run --machine wingtip --env "$E" \
  --toolchains nvhpc,nvhpc269 --modes 0,2 --workers 2 --compiles 2 --gpus "$G" --resume \
  --variants "$V" "${args[@]}" --out results/wingtip.$E.jsonl
python3 -I run_checks.py versions --machine wingtip --toolchains nvhpc,nvhpc269 --out results/versions.wingtip.jsonl > /dev/null
rm -rf /tmp/${USER}-t44
echo "done $(date -Is)"
