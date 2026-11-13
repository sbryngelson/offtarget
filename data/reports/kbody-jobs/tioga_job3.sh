#!/bin/bash
# on a Tioga compute node: regenerate the samples with the current code and run what is missing (the C programs)
ulimit -c 0
cd <site>/wt-kbody || exit 1
PY=/usr/tce/bin/python3
T0=$(date +%s)
$PY -I tools/campaigns/kbody.py gen --name pilot --kind pilot --n 300 --seed 1 || exit 1
$PY -I tools/campaigns/kbody.py gen --name nbhd --kind nbhd --base data/reports/kbody-jobs/base_dense.json || exit 1
export TMPDIR=/tmp/${USER}_kbtio3_$$
mkdir -p "$TMPDIR"
timeout -k 10 900 $PY -I tools/campaigns/kbody.py run --name nbhd --machine tioga --workers 8 --limit-s 800
timeout -k 10 1500 $PY -I tools/campaigns/kbody.py run --name pilot --machine tioga --workers 8 --limit-s 1400
T1=$(date +%s)
echo "{\"machine\": \"tioga\", \"nodes\": 1, \"steps\": \"pilot+nbhd rerun\", \"node\": \"$(hostname)\", \"wall_s\": $((T1 - T0)), \"gpu_h\": $($PY -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/kbody/ledger.jsonl
rm -rf "$TMPDIR"
echo finished3
