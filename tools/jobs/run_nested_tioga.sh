#!/bin/bash
# nested-data on Tioga (gcc_g90, MI250X) inside ONE foreground interactive job
# (this account has no pbatch on Tioga), from the copy tools/jobs/nested_remote.sh
# pushes (<campaign_lanes>/wt-nested):
#   ssh HOST 'builtin cd <campaign_lanes>/wt-nested && flux run -q pdebug -N1 -n1 --exclusive -t 60m \
#     --job-name=compile-test-nested-tio-N tools/jobs/run_nested_tioga.sh STEP NAME LIMIT_S'
# STEP: run | abd | c. (c) is another compute node: run it as a separate job
# placed off the node of (a) (--requires=-host:NODE); it refuses to start on a
# node that ran (a). One job at a time.
set -u
ulimit -c 0
cd "$(dirname "$0")/../.." || exit 1
S=$1; NAME=${2:-main}; LIM=${3:-1800}; W=${WORKERS:-8}
PY=${PY:-/usr/tce/bin/python3}
export TMPDIR=/tmp/${USER}_nested_tio_$$ GATE_TMP=/tmp/${USER}_nestedgate_tio_$$
mkdir -p "$TMPDIR" "$GATE_TMP" results/nested/logs
NODE=$(hostname)
T0=$(date +%s)
echo "host $NODE step $S start $(date -Is) rev $(cat .wingtip_rev 2>/dev/null)"
if [ "$S" = c ] && grep -qs "\"node\": \"${NODE%%.*}" results/nested/$NAME/gate_reruns.part.*.jsonl 2>/dev/null; then
  echo "refused: (c) is another node and $NODE ran (a)"; exit 2
fi
case $S in
  run) timeout -k 10 $((LIM + 120)) $PY -I tools/campaigns/nested.py run --name "$NAME" \
         --machine tioga --workers "$W" --limit-s "$LIM" ;;
  abd) timeout -k 10 $((LIM + 120)) $PY -I tools/campaigns/nested.py gate --name "$NAME" \
         --machine tioga --envs a,b,d --node same --workers "$W" ;;
  c) timeout -k 10 $((LIM + 120)) $PY -I tools/campaigns/nested.py gate --name "$NAME" \
         --machine tioga --envs c --node other --workers "$W" ;;
esac
T1=$(date +%s)
echo "{\"job\": \"${FLUX_JOB_ID:-}\", \"machine\": \"tioga\", \"nodes\": 1, \"step\": \"$S\", \"node\": \"$NODE\", \"wall_s\": $((T1 - T0)), \"gpu_h\": $($PY -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/nested/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo "done $(date -Is)"
