#!/bin/bash
# kernel-body pilot and the neighbourhood of the reduced program on Tuolumne (one pbatch node)
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
unset ROCR_VISIBLE_DEVICES
export TMPDIR=/tmp/${USER}_kbpilot_$$ GATE_TMP=/tmp/${USER}_kbgate_$$
mkdir -p "$TMPDIR" "$GATE_TMP"
T0=$(date +%s)
python3 -I tools/campaigns/kbody.py gen --name pilot --kind pilot --n 300 --seed 1 || exit 1
python3 -I tools/campaigns/kbody.py gen --name nbhd --kind nbhd --base data/reports/kbody-jobs/base_dense.json || exit 1
python3 -I tools/campaigns/kbody.py prerun --name nbhd --workers 8
python3 -I tools/campaigns/kbody.py prerun --name pilot --workers 8
timeout -k 10 1500 python3 -I tools/campaigns/kbody.py run --name nbhd --machine tuolumne --toolchains afar,cce19,cce20,cce21,cce21_4 --modes 1 --workers 20 --limit-s 1300
timeout -k 10 3300 python3 -I tools/campaigns/kbody.py run --name pilot --machine tuolumne --toolchains afar,cce21 --modes 0,1 --workers 24 --limit-s 3000
timeout -k 10 2400 python3 -I tools/campaigns/kbody.py run --name pilot --machine tuolumne --toolchains cce19,cce20,cce21_4 --modes 1 --workers 24 --limit-s 2200
T1=$(date +%s)
echo "{\"job\": \"${FLUX_JOB_ID:-}\", \"machine\": \"tuolumne\", \"nodes\": 1, \"steps\": \"pilot+nbhd\", \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/kbody/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo finished
