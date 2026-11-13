#!/bin/bash
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
unset ROCR_VISIBLE_DEVICES
export TMPDIR=/tmp/${USER}_mdd_$$
mkdir -p "$TMPDIR" results/malloc-dd
T0=$(date +%s)
timeout -k 10 3000 python3 -I tools/campaigns/malloc_dd.py reduce --launches 8
T1=$(date +%s)
echo "{\"job\": \"malloc-dd reduce\", \"machine\": \"tuolumne\", \"nodes\": 1, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/malloc-dd/ledger.jsonl
rm -rf "$TMPDIR"
echo finished
