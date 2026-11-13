#!/bin/bash
# the gate's environment (c): another node than (a) (which ran on tuolumne1021; this job is placed off it)
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
unset ROCR_VISIBLE_DEVICES
export TMPDIR=/tmp/${USER}_mdd4_$$ GATE_TMP=/tmp/${USER}_mdd4gate_$$
mkdir -p "$TMPDIR" "$GATE_TMP"
case "$(hostname)" in tuolumne1021*) echo "refused: (c) is another node and this is the node of (a)"; exit 2;; esac
T0=$(date +%s)
F=results/malloc-dd/final
CASES="afar-first-use-malloc=$F/repro.c afar-first-use-malloc-direct=$F/direct.c afar-first-use-malloc-warm=$F/warm.c afar-first-use-malloc-stack=$F/stack.c"
FCASES="afar-first-use-malloc-student=$F/student.f90 afar-first-use-malloc-student-elem=$F/student-elem.f90 afar-first-use-malloc-student-nocons=$F/student-nocons.f90"
timeout -k 10 1200 python3 -I tools/campaigns/malloc_dd.py gate $CASES $FCASES --tcs afar --modes 1 --envs c --node other
T1=$(date +%s)
echo "{\"job\": \"malloc-dd gate c\", \"machine\": \"tuolumne\", \"node\": \"$(hostname)\", \"nodes\": 1, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/malloc-dd/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo finished
