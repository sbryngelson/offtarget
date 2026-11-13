#!/bin/bash
# the 53-line finding file itself against the rebuilt libc variants
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
unset ROCR_VISIBLE_DEVICES
export TMPDIR=/tmp/${USER}_libcf_$$ GATE_TMP=/tmp/${USER}_libcfgate_$$
mkdir -p "$TMPDIR" "$GATE_TMP"
T0=$(date +%s)
python3 -I tools/campaigns/malloc_dd.py final
timeout -k 10 1200 python3 -I tools/campaigns/malloc_dd.py exp --only libc
T1=$(date +%s)
echo "{\"job\": \"malloc-dd libc A/B, finding file\", \"machine\": \"tuolumne\", \"node\": \"$(hostname)\", \"nodes\": 1, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/malloc-dd/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo finished
