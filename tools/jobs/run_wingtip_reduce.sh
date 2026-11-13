#!/bin/bash
# Run tools/reduce.py on wingtip (NVHPC, GCC sm_80) on one free GPU, inside
# the capped slice (tools/jobs/wingtip_cap.sh), nice; the harness runs one program
# at a time per GPU (COMPLIANT_RUN_SLOTS=1, its own lock). The GPU is picked
# by nvidia-smi as the other run_wingtip*.sh do and held by this script's
# lock file against a second queue of this script; another agent's script
# choosing the same GPU at the same instant is not excluded. From a copy of
# the tree on wingtip:
#   tools/jobs/run_wingtip_reduce.sh REDUCE_ARGS...        # see tools/reduce.py --help
#   setsid nohup tools/jobs/run_wingtip_reduce.sh ... > results/reduce/<name>.log 2>&1 < /dev/null &
# A free GPU has no process of anyone and under 100 MiB in use; the wait for
# one is bounded by GPU_WAIT_S (default one hour), after which the script
# exits 3 and runs nothing. PY names the Python to use (default python3; the
# lane's environment is listed in docs/tooling/wingtip.md).
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
set -u
ulimit -c 0
cd "$(dirname "$0")/../.." || exit 1
[ $# -ge 1 ] || { echo "usage: $0 REDUCE_ARGS... (tools/reduce.py --help)" >&2; exit 2; }
PY=${PY:-python3}

free_gpu() {   # sets G to a free GPU whose lock this shell now holds (fd 9)
  local end=$(( $(date +%s) + ${GPU_WAIT_S:-3600} )) g used apps
  while [ "$(date +%s)" -lt "$end" ]; do
    for g in 0 1 2 3; do
      used=$(nvidia-smi -i "$g" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
      apps=$(nvidia-smi -i "$g" --query-compute-apps=pid --format=csv,noheader | grep -c .)
      [ "$used" -lt 100 ] && [ "$apps" -eq 0 ] || continue
      exec 9>"/tmp/${USER}_reduce_gpu$g.lock"
      if flock -n 9; then G=$g; return 0; fi
      exec 9>&-
    done
    sleep "${POLL_S:-60}"
  done
  return 1
}

free_gpu || { echo "[$(date -Is)] no free GPU within ${GPU_WAIT_S:-3600} s: nothing run"; exit 3; }
echo "[$(date -Is)] reduce on $(hostname) GPU $G rev $(cat .wingtip_rev 2>/dev/null): $*"
export CUDA_VISIBLE_DEVICES=$G COMPLIANT_RUN_SLOTS=1
nice -n 10 "$PY" -I tools/reduce.py "$@"
rc=$?
echo "[$(date -Is)] reduce exit $rc"
exit $rc
