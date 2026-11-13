#!/bin/bash
cd "$(dirname "$0")/../../.." || exit 1
python3 -I tools/campaigns/kbody.py gen --name red2 --kind cfgs --cfgs .superpowers/kbody/red2.json || exit 1
python3 -I tools/campaigns/kbody.py prerun --name red2 --workers 8
export PY=python3
T0=$(date +%s)
python3 -I tools/campaigns/kbody.py rate --name red2 --machine tuolumne --toolchains afar --modes 1 --runs 8 --workers 4
T1=$(date +%s)
echo "{\"job\": \"red2-rate\", \"machine\": \"tuolumne\", \"nodes\": 1, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/kbody/ledger.jsonl
echo finished
