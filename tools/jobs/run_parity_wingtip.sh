#!/bin/bash
# Coverage parity on wingtip (tools/campaigns/parity.py): one queue of steps, each on a
# GPU checked free right before it starts (no process of anyone, under 100
# MiB) and held by a lock file while it runs, so two queues of this lane
# never share one. Inside the capped slice (wingtip_cap.sh), nice, the
# per-GPU run lock (COMPLIANT_RUN_SLOTS=1), WORKERS compiles (at most 2;
# two queues at most: 4 compiles in all). From the copy that
# tools/jobs/parity_remote.sh pushes.
#   setsid nohup tools/jobs/run_parity_wingtip.sh LIMIT_S STEP [STEP...] \
#     > results/parity/logs/<queue>.log 2>&1 < /dev/null &
# Steps:
#   harvest:SET:TC          tools/campaigns/harvest.py run (HARVEST_SET; harvest-known
#                           through tools/campaigns/harvest_known.py via49a), copy mode
#   hgate:SET:TC:ENVS:K     the gate of that run's failing rows, shard K/2:
#                           tools/campaigns/harvest.py (harvest, harvest2) runs (a),
#                           (b), (d) of half K and (c) of the other half;
#                           harvest-known (the gate) runs ENVS of
#                           half K, so its (c) is of half K too
#   fuzz:STRATUM:TC[+TC]    tools/campaigns/fuzz.py run of the sample's seeds
#   stress:RUN:TC:ARGS      tools/campaigns/stress.py sweep (ARGS: + for space)
#   apps:TC                 tools/campaigns/app_bench.py run, copy mode
#   pgate:CAMP:ENVS:K[:CELLS] tools/campaigns/parity.py gate-run (fuzz or stress) shard K/2
#                           (CELLS: a c-cells file, only those rows)
#   site:ENV:GCC            tools/jobs/run_site_matrix.sh wingtip ENV on this GPU (GCC=1: gcc_sm80,
#                           else NVHPC); ENV c avoids the GPU of ENV a
#   cmd:ANYTHING            one command (+ for space)
# LIMIT_S bounds each step (timeout --kill-after); a step that finds no free
# GPU within GPU_WAIT_S (default 4 h) stops the queue.
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
set -u
ulimit -c 0
cd "$(dirname "$0")/../.." || exit 1
LIM=$1; shift
W=${WORKERS:-2}
[ "$W" -le 2 ] || { echo "at most 2 workers per queue"; exit 2; }
PY=${PY:-python3}
mkdir -p results/parity/logs
LEDGER=results/parity/ledger.wingtip.jsonl
echo "start $(date -Is) on $(hostname) rev $(cat .wingtip_rev 2>/dev/null) steps $*"

free_gpu() {   # sets G to a free GPU whose lock this shell now holds (fd 9)
  local end=$(( $(date +%s) + ${GPU_WAIT_S:-14400} )) g used apps
  while [ "$(date +%s)" -lt "$end" ]; do
    for g in 0 1 2 3; do
      [ "$g" = "${AVOID:-x}" ] && continue
      used=$(nvidia-smi -i "$g" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')
      apps=$(nvidia-smi -i "$g" --query-compute-apps=pid --format=csv,noheader | grep -c .)
      [ "$used" -lt 100 ] && [ "$apps" -eq 0 ] || continue
      exec 9>"/tmp/${USER}_parity_gpu$g.lock"
      if flock -n 9; then G=$g; return 0; fi
      exec 9>&-
    done
    sleep "${POLL_S:-60}"
  done
  return 1
}

declare -A CAN_DONE
sample_seeds() {   # STRATUM -> "gen base... | seeds..."
  "$PY" -I -c '
import json, sys
s = json.load(open("catalog/parity_fuzz_sample.json"))["strata"][sys.argv[1]]
print(s["gen_version"], " ".join(s["base"]), "|", " ".join(map(str, s["seeds"])))' "$1"
}

for step in "$@"; do
  IFS=: read -r kind a b c d <<< "$step"
  # the gate's (c) runs on another GPU than (a): the GPU of the other half's
  # (a), (b), (d) step is avoided (results/parity/gpu_of/<kind>.<set>.<half>)
  AVOID=""
  case $kind in
    hgate)
      # the half whose (a) this (c) reruns (parity: harvest-known's
      # (c) of half K had avoided half K+1's GPU and ran on its own (a)'s)
      h=$(( (d + 1) % 2 )); [ "$a" = harvest-known ] && h=$d
      [ "$c" = c ] && AVOID=$(cat "results/parity/gpu_of/hgate.$a.$h" 2>/dev/null) ;;
    pgate) [ "$b" = c ] && AVOID=$(cat "results/parity/gpu_of/pgate.$a.$c" 2>/dev/null) ;;
    site) [ "$a" = c ] && AVOID=$(cat "results/parity/gpu_of/site.a.$b" 2>/dev/null) ;;
  esac
  free_gpu || { echo "[$(date -Is)] no free GPU for $step: stop"; exit 3; }
  export CUDA_VISIBLE_DEVICES=$G COMPLIANT_RUN_SLOTS=1
  export TMPDIR=/tmp/${USER}_par_$$_$G GATE_TMP=/tmp/${USER}_pargate_$$_$G
  export STRESS_TMP=$TMPDIR/stress
  mkdir -p "$TMPDIR" "$GATE_TMP" "$STRESS_TMP"
  mkdir -p results/parity/gpu_of
  case $kind in
    hgate) [ "$c" != c ] && echo "$G" > "results/parity/gpu_of/hgate.$a.$d" ;;
    pgate) [ "$b" != c ] && echo "$G" > "results/parity/gpu_of/pgate.$a.$c" ;;
    site) [ "$a" = a ] && echo "$G" > "results/parity/gpu_of/site.a.$b" ;;
  esac
  T0=$(date +%s)
  echo "[$(date -Is)] GPU $G: $step"
  run() { nice -n 10 timeout --kill-after=30 "$LIM" "$@"; }
  case $kind in
    harvest)
      if [ "$a" = harvest-known ]; then
        run "$PY" -I tools/campaigns/harvest_known.py via49a run --name parity --machine wingtip \
          --toolchains "$b" --modes 0 --workers "$W" --limit-s "$LIM" ${RETRY:+--retry-errors}
      else
        HARVEST_SET=$a run "$PY" -I tools/campaigns/harvest.py run --name parity --machine wingtip \
          --toolchains "$b" --modes 0 --workers "$W" --limit-s "$LIM" ${RETRY:+--retry-errors}
      fi ;;
    hgate)
      if [ "$a" = harvest-known ]; then
        run "$PY" -I tools/campaigns/harvest_known.py via49a gate --name parity --machine wingtip \
          --envs "$c" --shard "$d/2" --workers "$W" --limit-s "$LIM"
      else
        HARVEST_SET=$a run "$PY" -I tools/campaigns/harvest.py gate --name parity --machine wingtip \
          --envs "$c" --shard "$d/2" --workers "$W" --limit-s "$LIM"
      fi ;;
    fuzz)
      read -r gv rest <<< "$(sample_seeds "$a")"
      base=${rest%%|*}; seeds=${rest#*|}
      # the canaries once per toolchain set and queue: with its first fuzz run
      can=()
      if [ -n "${CAN_DONE[$b]:-}" ]; then
        can=(--canaries-exempt "this lane's canaries for these toolchains ran with ${CAN_DONE[$b]} (same queue, same host)")
      fi
      COMPLIANT_FUZZ_CHECKS=results/parity/fuzz/checks/$a.jsonl run "$PY" -I tools/campaigns/fuzz.py run \
        --run-id "par-$a-${b//+/-}" --seeds $seeds --gen-version "$gv" \
        ${base:+--base-features $base} --xnack 0 --workers "$W" --toolchains ${b//+/ } "${can[@]}"
      frc=$?
      [ "$frc" -eq 0 ] && [ -z "${CAN_DONE[$b]:-}" ] && CAN_DONE[$b]=par-$a-${b//+/-}
      (exit "$frc") ;;
    stress)
      COMPLIANT_PRERUN_STORED=results/parity/stress-checked/programs.jsonl \
        run "$PY" -I tools/campaigns/stress.py sweep --run "$a" --no-check --workers "$W" \
        --mem-gib 16 --toolchains "$b" --modes 0 ${c//+/ } ;;
    pgate)
      # the fuzz or stress gate (tools/campaigns/parity.py gate-run): ENVS of shard K/2
      run "$PY" -I tools/campaigns/parity.py gate-run --campaign "$a" --machine wingtip \
        --envs "$b" --shard "$c/2" ${d:+--cells "$d"} --workers "$W" --limit-s "${LIMIT_GATE:-$LIM}" ;;
    site)
      # run_site_matrix.sh checks and selects the GPU by its physical index
      ( unset CUDA_VISIBLE_DEVICES COMPLIANT_RUN_SLOTS
        if [ "$b" = 1 ]; then GCC=1 run bash tools/jobs/run_site_matrix.sh wingtip "$a" "$G"
        else run bash tools/jobs/run_site_matrix.sh wingtip "$a" "$G"; fi ) ;;
    apps)
      run "$PY" -I tools/campaigns/app_bench.py run --toolchains "$a" --modes copy --jobs "$W" ;;
    cmd)
      run ${a//+/ } ;;
    *) echo "unknown step $step" ;;
  esac
  rc=$?
  exec 9>&-
  rm -rf "$TMPDIR" "$GATE_TMP"
  T1=$(date +%s)
  echo "{\"step\": \"$step\", \"gpu\": $G, \"rc\": $rc, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(($T1-$T0)/3600, 3))"), \"end\": \"$(date -Is)\"}" >> "$LEDGER"
  echo "[$(date -Is)] GPU $G: $step rc=$rc $((T1 - T0)) s"
done
echo "all done $(date -Is)"
