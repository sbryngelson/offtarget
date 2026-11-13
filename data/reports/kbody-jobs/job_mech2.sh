#!/bin/bash
# XCC confinement, bare instructions before free, patch forms (rmw, rmwrel), allocation sizes: the maintainer's sources, harness launches
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
unset ROCR_VISIBLE_DEVICES
export TMPDIR=/tmp/${USER}_mech2_$$ GATE_TMP=/tmp/${USER}_mech2gate_$$
mkdir -p "$TMPDIR" "$GATE_TMP"
T0=$(date +%s)
for g in xcc bare patchform sizes; do timeout -k 10 400 python3 -I tools/campaigns/malloc_dd.py exp --only $g; done
T1=$(date +%s)
echo "{\"job\": \"malloc-dd mechanism 2 (xcc, bare, patch forms, sizes)\", \"machine\": \"tuolumne\", \"node\": \"$(hostname)\", \"nodes\": 1, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/malloc-dd/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo finished
