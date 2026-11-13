#!/bin/bash
# device-heap-temporary sample: every write idiom x 4 contexts, AFAR at HSA_XNACK=1 and 0 on one pbatch node;
# then the detector (compile only) over the heap sample and every Fortran program set we hold
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
unset ROCR_VISIBLE_DEVICES
export TMPDIR=/tmp/${USER}_kbheap_$$ GATE_TMP=/tmp/${USER}_kbheapgate_$$
mkdir -p "$TMPDIR" "$GATE_TMP"
T0=$(date +%s)
python3 -I tools/campaigns/kbody.py gen --name heap --kind heap || exit 1
python3 -I tools/campaigns/kbody.py prerun --name heap --workers 8
timeout -k 10 1500 python3 -I tools/campaigns/kbody.py rate --name heap --machine tuolumne --toolchains afar --modes 1 --runs 6 --workers 4
T1=$(date +%s)
echo "{\"job\": \"${FLUX_JOB_ID:-}\", \"machine\": \"tuolumne\", \"nodes\": 1, \"steps\": \"heap rate\", \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/kbody/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo finished
