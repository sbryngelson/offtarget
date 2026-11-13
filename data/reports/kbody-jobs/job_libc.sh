#!/bin/bash
# upstream fix test: the allocator's libc rebuilt from AFAR's commit (unmodified / release fence / release+acquire), C reproducer and the student's Fortran
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
unset ROCR_VISIBLE_DEVICES
export TMPDIR=/tmp/${USER}_libc_$$ GATE_TMP=/tmp/${USER}_libcgate_$$
mkdir -p "$TMPDIR" "$GATE_TMP" results/malloc-dd
T0=$(date +%s)
timeout -k 10 1200 python3 -I tools/campaigns/malloc_dd.py exp --only libc
timeout -k 10 900 python3 -I tools/campaigns/malloc_dd.py libc
T1=$(date +%s)
echo "{\"job\": \"malloc-dd libc A/B\", \"machine\": \"tuolumne\", \"node\": \"$(hostname)\", \"nodes\": 1, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/malloc-dd/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo finished
