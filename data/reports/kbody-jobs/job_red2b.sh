#!/bin/bash
cd "$(dirname "$0")/../../.." || exit 1
python3 -I tools/campaigns/kbody.py gen --name red2b --kind cfgs --cfgs .superpowers/kbody/red2b.json || exit 1
T0=$(date +%s)
timeout -k 10 780 python3 -I tools/campaigns/kbody.py rate --name red2b --machine tuolumne --toolchains afar --modes 1 --runs 6 --workers 8
T1=$(date +%s)
echo "{\"job\": \"red2b-rate (pdebug)\", \"machine\": \"tuolumne\", \"nodes\": 1, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/kbody/ledger.jsonl
echo finished
