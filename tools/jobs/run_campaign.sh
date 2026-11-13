#!/bin/bash
# A registered campaign (offload/engine/campaign.py; tools/campaign.py) on a flux
# machine, ONE node per job. Generalizes tools/jobs/run_nested.sh and
# tools/jobs/run_nested_tioga.sh, which stay as the records of the nested runs.
#   tools/jobs/run_campaign.sh CAMPAIGN STEPS [NAME] [LIMIT_S] [WORKERS]
# STEPS: any of prerun | run | abd | c, in order ("run abd" in one job).
# MACHINE (default tuolumne) is the catalog machine the toolchains belong to;
# PY the Python (Tioga: /usr/tce/bin/python3). Resumable: each step appends to
# results/CAMPAIGN/NAME/*.part.* files, the job to results/CAMPAIGN/ledger.jsonl
# (GPU-hours = nodes x 4 x hours). `tools/campaign.py CAMPAIGN submit --machine M`
# prints the matching command.
# Batch work goes to pbatch:
#   flux batch -q pbatch -N1 -t 60m --setattr=thp=always \
#     --job-name=CAMPAIGN-run --output=results/CAMPAIGN/logs/run.{{id}}.log \
#     tools/jobs/run_campaign.sh CAMPAIGN "run abd" [NAME] [LIMIT_S] [WORKERS]
# When pbatch is starved the same script runs as one foreground pdebug job
# (<= 30 min, one at a time, named like a compile job):
#   flux run -q pdebug -N1 -n1 --exclusive -t 30m --setattr=thp=always \
#     --job-name=compile-test-CAMPAIGN-N [--requires=-host:NODE] \
#     tools/jobs/run_campaign.sh CAMPAIGN STEPS [NAME] [LIMIT_S] [WORKERS]
# Tioga (no pbatch for this account): from the copy tools/jobs/campaign_remote.sh
# pushes, one foreground pdebug job (<= 60 min) at a time:
#   ssh tio 'builtin cd LANE && MACHINE=tioga PY=/usr/tce/bin/python3 flux run -q pdebug -N1 -n1 \
#     --exclusive -t 60m --job-name=compile-test-CAMPAIGN-tio tools/jobs/run_campaign.sh CAMPAIGN STEP NAME LIMIT_S'
# RUN_TCS=a,b limits the run step to those toolchains; RUN_SHARD=k/m takes
# every m-th remaining cell (two jobs at once share the cells without overlap).
# Step c is the gate's "another node": run it as a separate job placed off the
# node of (a) (--requires=-host:...); it refuses to start on a node that ran
# step abd. LIMIT_S bounds the whole job: each step gets what is left.
ulimit -c 0
cd "${CAMPAIGN_ROOT:-$PWD}" || exit 1
[ -f tools/campaign.py ] || { echo "not a repository root: $PWD"; exit 1; }
unset ROCR_VISIBLE_DEVICES
CAMP=$1; STEPS=$2; NAME=${3:-main}; LIM=${4:-1500}; W=${5:-24}
[ -n "$CAMP" ] && [ -n "$STEPS" ] || { echo "usage: $0 CAMPAIGN STEPS [NAME] [LIMIT_S] [WORKERS]"; exit 2; }
M=${MACHINE:-tuolumne}
PY=${PY:-python3}
export TMPDIR=/tmp/${USER}_${CAMP}_$$ GATE_TMP=/tmp/${USER}_${CAMP}gate_$$
mkdir -p "$TMPDIR" "$GATE_TMP" "results/$CAMP/logs"
T0=$(date +%s)
END=$((T0 + LIM))
NODE=$(hostname)
echo "host $NODE campaign $CAMP machine $M steps '$STEPS' start $(date -Is) rev $(git rev-parse --short HEAD 2>/dev/null || cat .wingtip_rev 2>/dev/null)"
for S in $STEPS; do
  REM=$((END - $(date +%s)))
  [ "$REM" -gt 60 ] || { echo "no time left for $S"; break; }
  if [ "$S" = c ] && grep -qs "\"node\": \"${NODE%%.*}" "results/$CAMP/$NAME"/gate_reruns.part.*.jsonl 2>/dev/null; then
    echo "refused: (c) is another node and $NODE ran (a)"; continue
  fi
  case $S in
    prerun) timeout -k 10 $((REM + 60)) $PY -I tools/campaign.py "$CAMP" prerun --name "$NAME" --workers "${PRERUN_W:-8}" ;;
    run) timeout -k 10 $((REM + 120)) $PY -I tools/campaign.py "$CAMP" run --name "$NAME" \
           --machine "$M" --workers "$W" --limit-s "$REM" \
           ${RUN_TCS:+--toolchains "$RUN_TCS"} ${RUN_SHARD:+--shard "$RUN_SHARD"} ;;
    abd) timeout -k 10 $((REM + 120)) $PY -I tools/campaign.py "$CAMP" gate --name "$NAME" \
           --machine "$M" --envs a,b,d --node "${GATE_NODE:-same}" ${GATE_STORED_ON:+--stored-on "$GATE_STORED_ON"} --workers "${GATE_W:-8}" ;;
    c) timeout -k 10 $((REM + 120)) $PY -I tools/campaign.py "$CAMP" gate --name "$NAME" \
           --machine "$M" --envs c --node other ${GATE_STORED_ON:+--stored-on "$GATE_STORED_ON"} --workers "${GATE_W:-8}" ;;
    *) echo "unknown step $S (prerun | run | abd | c)" ;;
  esac
done
T1=$(date +%s)
echo "{\"job\": \"${FLUX_JOB_ID:-}\", \"machine\": \"$M\", \"nodes\": 1, \"steps\": \"$STEPS\", \"node\": \"$NODE\", \"wall_s\": $((T1 - T0)), \"gpu_h\": $($PY -c "print(round(4*($T1-$T0)/3600, 3))")}" >> "results/$CAMP/ledger.jsonl"
rm -rf "$TMPDIR" "$GATE_TMP"
echo "done $(date -Is)"
