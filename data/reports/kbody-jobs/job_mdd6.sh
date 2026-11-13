#!/bin/bash
# the mechanism experiments (read-back, double allocation, flush, fences, omp_alloc), the fence controls and the ISA excerpt
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
unset ROCR_VISIBLE_DEVICES
export TMPDIR=/tmp/${USER}_mdd6_$$ GATE_TMP=/tmp/${USER}_mdd6gate_$$
mkdir -p "$TMPDIR" "$GATE_TMP" results/malloc-dd
T0=$(date +%s)
python3 -I tools/campaigns/malloc_dd.py final
F=results/malloc-dd/final
cp $F/fence.c $F/afar-first-use-malloc-fence.c; cp $F/flush.c $F/afar-first-use-malloc-flush.c
timeout -k 10 1500 python3 -I tools/campaigns/malloc_dd.py exp --only mechanism --launches 10
timeout -k 10 600 python3 -I tools/campaigns/malloc_dd.py rows afar-first-use-malloc-fence=$F/afar-first-use-malloc-fence.c afar-first-use-malloc-flush=$F/afar-first-use-malloc-flush.c --tcs afar --modes 1 --repeats 10
timeout -k 10 600 python3 -I tools/campaigns/malloc_dd.py isa
T1=$(date +%s)
echo "{\"job\": \"malloc-dd mechanism\", \"machine\": \"tuolumne\", \"node\": \"$(hostname)\", \"nodes\": 1, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/malloc-dd/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo finished
