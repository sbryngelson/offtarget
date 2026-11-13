#!/bin/bash
# nested-data (tools/campaigns/nested.py) on a flux machine, ONE node per job.
# STEPS: any of prerun | run | abd | c, in order ("run abd" in one job).
# Resumable; each step appends to results/nested/NAME/*.part.* files and the
# job to results/nested/ledger.jsonl (GPU-hours = nodes x 4 x hours).
# Batch work goes to pbatch:
#   flux batch -q pbatch -N1 -t 60m --setattr=thp=always \
#     --job-name=nested-run --output=results/nested/logs/run.{{id}}.log \
#     tools/jobs/run_nested.sh "run abd" [NAME] [LIMIT_S] [WORKERS]
# When pbatch is starved the same script runs as one foreground pdebug job
# (<= 30 min, one at a time, named like a compile job):
#   flux run -q pdebug -N1 -n1 --exclusive -t 30m --setattr=thp=always \
#     --job-name=compile-test-nested-N [--requires=-host:NODE] \
#     tools/jobs/run_nested.sh STEPS [NAME] [LIMIT_S] [WORKERS]
# RUN_TCS=afar,cce21_4 limits the run step to those toolchains; RUN_SHARD=k/m takes
# every m-th remaining cell (two jobs at once share the cells without overlap).
# Step c is the gate's "another node": run it as a separate job placed off
# the node of (a) (--requires=-host:...); it refuses to start on a node that
# ran step abd. LIMIT_S bounds the whole job: each step gets what is left.
ulimit -c 0
cd "${NESTED_ROOT:-$PWD}" || exit 1
[ -f tools/campaigns/nested.py ] || { echo "not a repository root: $PWD"; exit 1; }
unset ROCR_VISIBLE_DEVICES
STEPS=$1; NAME=${2:-main}; LIM=${3:-1500}; W=${4:-24}
PY=${PY:-python3}
export TMPDIR=/tmp/${USER}_nested_$$ GATE_TMP=/tmp/${USER}_nestedgate_$$
mkdir -p "$TMPDIR" "$GATE_TMP" results/nested/logs
T0=$(date +%s)
END=$((T0 + LIM))
NODE=$(hostname)
echo "host $NODE steps '$STEPS' start $(date -Is) git $(git rev-parse --short HEAD)"
for S in $STEPS; do
  REM=$((END - $(date +%s)))
  [ "$REM" -gt 60 ] || { echo "no time left for $S"; break; }
  if [ "$S" = c ] && grep -qs "\"node\": \"${NODE%%.*}" results/nested/$NAME/gate_reruns.part.*.jsonl 2>/dev/null; then
    echo "refused: (c) is another node and $NODE ran (a)"; continue
  fi
  case $S in
    prerun) timeout -k 10 $((REM + 60)) $PY -I tools/campaigns/nested.py prerun --name "$NAME" --workers 8 ;;
    run) timeout -k 10 $((REM + 120)) $PY -I tools/campaigns/nested.py run --name "$NAME" \
           --machine tuolumne --workers "$W" --limit-s "$REM" \
           ${RUN_TCS:+--toolchains "$RUN_TCS"} ${RUN_SHARD:+--shard "$RUN_SHARD"} ;;
    abd) timeout -k 10 $((REM + 120)) $PY -I tools/campaigns/nested.py gate --name "$NAME" \
           --machine tuolumne --envs a,b,d --node "${GATE_NODE:-same}" ${GATE_STORED_ON:+--stored-on "$GATE_STORED_ON"} --workers "${GATE_W:-8}" ;;
    c) timeout -k 10 $((REM + 120)) $PY -I tools/campaigns/nested.py gate --name "$NAME" \
           --machine tuolumne --envs c --node other ${GATE_STORED_ON:+--stored-on "$GATE_STORED_ON"} --workers "${GATE_W:-8}" ;;
  esac
done
T1=$(date +%s)
echo "{\"job\": \"${FLUX_JOB_ID:-}\", \"machine\": \"tuolumne\", \"nodes\": 1, \"steps\": \"$STEPS\", \"node\": \"$NODE\", \"wall_s\": $((T1 - T0)), \"gpu_h\": $($PY -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/nested/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo "done $(date -Is)"
