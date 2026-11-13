#!/bin/bash
# Coverage parity on Tioga (gcc_g90; tools/campaigns/parity.py), inside ONE foreground
# interactive job (this account has no pbatch on Tioga), from the copy that
# tools/jobs/parity_remote.sh pushes:
#   flux run -q pdebug -N1 -n1 --exclusive -t 60m --job-name=compile-test-gcc-parity-N \
#     tools/jobs/run_parity_tioga.sh LIMIT_S GCD:STEP [GCD:STEP...]
# Each GCD:STEP runs at once on its own GCD (ROCR_VISIBLE_DEVICES), WORKERS
# (default 8) workers; the steps of one GCD separated by "@" run in order.
# The gate's (c) is another compute node (offload/engine/gate.py; not
# another GCD): a job with an hgate
# or pgate step whose ENVS hold c needs A_HOSTS, the nodes (comma
# separated) where those rows' (a) ran, and the job placed off them
# (flux --requires=-host:...); it refuses to start on one of them.
# Steps (as tools/jobs/run_parity_wingtip.sh): harvest:SET:TC, hgate:SET:TC:ENVS:K,
# fuzz:STRATUM:TC, stress:RUN:TC:ARGS, apps:TC, pgate:CAMP:ENVS:K[:CELLS], cmd:ANYTHING. LIMIT_S
# bounds the whole job's steps (each gets what is left).
set -u
ulimit -c 0
cd "$(dirname "$0")/../.." || exit 1
LIM=$1; shift
W=${WORKERS:-8}
PY=${PY:-/usr/tce/bin/python3}
END=$(( $(date +%s) + LIM ))
NODE=$(hostname)
for item in "$@"; do
  IFS=@ read -ra list <<< "${item#*:}"
  for s in "${list[@]}"; do
    IFS=: read -r kind a b c d <<< "$s"
    case $kind in hgate) e=$c ;; pgate) e=$b ;; *) e= ;; esac
    case ",$e," in *,c,*)
      [ -n "${A_HOSTS:-}" ] || { echo "refused: $s needs A_HOSTS (the nodes of (a))"; exit 2; }
      case ",$A_HOSTS," in *",${NODE%%.*},"*)
        echo "refused: $s on $NODE, a node of (a) ($A_HOSTS); (c) is another node"; exit 2 ;; esac ;;
    esac
  done
done
mkdir -p results/parity/logs
LEDGER=results/parity/ledger.tioga.jsonl
echo "start $(date -Is) on $NODE rev $(cat .wingtip_rev 2>/dev/null) items $*"

one() {   # GCD STEP
  local G=$1 step=$2 kind a b c d REM T0 T1 rc
  IFS=: read -r kind a b c d <<< "$step"
  export ROCR_VISIBLE_DEVICES=$G
  export TMPDIR=/tmp/${USER}_par_$$_$G GATE_TMP=/tmp/${USER}_pargate_$$_$G
  export STRESS_TMP=$TMPDIR/stress
  mkdir -p "$TMPDIR" "$GATE_TMP" "$STRESS_TMP"
  REM=$((END - $(date +%s)))
  [ "$REM" -gt 60 ] || { echo "[$(date -Is)] GCD $G: no time for $step"; return 0; }
  T0=$(date +%s)
  echo "[$(date -Is)] GCD $G: $step"
  run() { timeout --kill-after=30 "$REM" "$@"; }
  case $kind in
    hgate|pgate)
      # the gate's (c) is "another node": here another GCD of the node. The
      # gate names a rerun's node by CUDA_VISIBLE_DEVICES under the run lock
      # (tools/campaigns/gate.py _here, harvest.py gate); libgomp's GCN plugin (HSA)
      # does not read it: ROCR_VISIBLE_DEVICES picks the GCD
      export COMPLIANT_RUN_SLOTS=1 CUDA_VISIBLE_DEVICES=$G ;;
  esac
  case $kind in
    harvest)
      if [ "$a" = harvest-known ]; then
        run "$PY" -I tools/campaigns/harvest_known.py via49a run --name parity --machine tioga \
          --toolchains "$b" --modes 0 --workers "$W" --limit-s "$REM" ${RETRY:+--retry-errors}
      else
        HARVEST_SET=$a run "$PY" -I tools/campaigns/harvest.py run --name parity --machine tioga \
          --toolchains "$b" --modes 0 --workers "$W" --limit-s "$REM" ${RETRY:+--retry-errors}
      fi ;;
    hgate)
      if [ "$a" = harvest-known ]; then
        run "$PY" -I tools/campaigns/harvest_known.py via49a gate --name parity --machine tioga \
          --envs "$c" --shard "$d/2" --workers "$W" --limit-s "$REM"
      else
        HARVEST_SET=$a run "$PY" -I tools/campaigns/harvest.py gate --name parity --machine tioga \
          --envs "$c" --shard "$d/2" --workers "$W" --limit-s "$REM"
      fi ;;
    fuzz)
      local gv rest base seeds
      read -r gv rest <<< "$("$PY" -I -c '
import json, sys
s = json.load(open("catalog/parity_fuzz_sample.json"))["strata"][sys.argv[1]]
print(s["gen_version"], " ".join(s["base"]), "|", " ".join(map(str, s["seeds"])))' "$a")"
      base=${rest%%|*}; seeds=${rest#*|}
      COMPLIANT_FUZZ_CHECKS=results/parity/fuzz/checks/$a.jsonl run "$PY" -I tools/campaigns/fuzz.py run \
        --run-id "par-$a-$b" --seeds $seeds --gen-version "$gv" \
        ${base:+--base-features $base} --xnack 0 --workers "$W" --toolchains "$b" ;;
    stress)
      COMPLIANT_PRERUN_STORED=results/parity/stress-checked/programs.jsonl \
        run "$PY" -I tools/campaigns/stress.py sweep --run "$a" --no-check --workers "$W" \
        --mem-gib 16 --toolchains "$b" --modes 0 ${c//+/ } ;;
    pgate)
      # the fuzz or stress gate (tools/campaigns/parity.py gate-run): ENVS of shard K/2
      run "$PY" -I tools/campaigns/parity.py gate-run --campaign "$a" --machine tioga \
        --envs "$b" --shard "$c/2" ${d:+--cells "$d"} --workers "$W" --limit-s "$REM" ;;
    apps)
      run "$PY" -I tools/campaigns/app_bench.py run --toolchains "$a" --modes copy --jobs "$W" ;;
    cmd)
      run ${a//+/ } ;;
    *) echo "unknown step $step" ;;
  esac
  rc=$?
  rm -rf "$TMPDIR" "$GATE_TMP"
  T1=$(date +%s)
  echo "{\"step\": \"$step\", \"node\": \"$NODE\", \"gcd\": $G, \"rc\": $rc, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(($T1-$T0)/3600/2, 3))"), \"end\": \"$(date -Is)\"}" >> "$LEDGER"
  echo "[$(date -Is)] GCD $G: $step rc=$rc $((T1 - T0)) s"
}

for item in "$@"; do
  G=${item%%:*}; steps=${item#*:}
  (
    IFS=@ read -ra list <<< "$steps"
    for s in "${list[@]}"; do one "$G" "$s"; done
  ) > "results/parity/logs/tioga.$NODE.gcd$G.log" 2>&1 &
done
wait
echo "all done $(date -Is)"
