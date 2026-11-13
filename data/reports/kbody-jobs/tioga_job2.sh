#!/bin/bash
# on a Tioga compute node: the rest of the trial (shards 1 and 2 of 3) on GCC 16.2 (gfx90a)
ulimit -c 0
cd <site>/wt-kbody || exit 1
PY=/usr/tce/bin/python3
T0=$(date +%s)
export TMPDIR=/tmp/${USER}_kbtio2_$$
mkdir -p "$TMPDIR"
timeout -k 10 1500 $PY -I tools/campaigns/kbody.py run --name pilot --machine tioga --workers 8 --shard 1/3 --limit-s 1400
timeout -k 10 1500 $PY -I tools/campaigns/kbody.py run --name pilot --machine tioga --workers 8 --shard 2/3 --limit-s 1400
T1=$(date +%s)
echo "{\"machine\": \"tioga\", \"nodes\": 1, \"steps\": \"pilot rest\", \"node\": \"$(hostname)\", \"wall_s\": $((T1 - T0)), \"gpu_h\": $($PY -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/kbody/ledger.jsonl
rm -rf "$TMPDIR"
echo finished2
