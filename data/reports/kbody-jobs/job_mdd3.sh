#!/bin/bash
# stage 3 of the device-malloc reduction (more fresh launches, the controls, XNACK=0), the Fortran cases, the gate (a, b, d)
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
unset ROCR_VISIBLE_DEVICES
export TMPDIR=/tmp/${USER}_mdd3_$$ GATE_TMP=/tmp/${USER}_mdd3gate_$$
mkdir -p "$TMPDIR" "$GATE_TMP" results/malloc-dd
T0=$(date +%s)
F=results/malloc-dd/final
CASES="afar-first-use-malloc=$F/repro.c afar-first-use-malloc-direct=$F/direct.c afar-first-use-malloc-warm=$F/warm.c afar-first-use-malloc-stack=$F/stack.c"
FCASES="afar-first-use-malloc-student=$F/student.f90 afar-first-use-malloc-student-elem=$F/student-elem.f90 afar-first-use-malloc-student-nocons=$F/student-nocons.f90"
timeout -k 10 1500 python3 -I tools/campaigns/malloc_dd.py stage3 --launches 8
timeout -k 10 600 python3 -I tools/campaigns/malloc_dd.py rows $FCASES --tcs afar --modes 1 --repeats 10
echo "== gate a,b,d"
timeout -k 10 900 python3 -I tools/campaigns/malloc_dd.py gate $CASES $FCASES --tcs afar --modes 1 --envs a,b,d
T1=$(date +%s)
echo "{\"job\": \"malloc-dd stage 3 + gate abd\", \"machine\": \"tuolumne\", \"node\": \"$(hostname)\", \"nodes\": 1, \"wall_s\": $((T1 - T0)), \"gpu_h\": $(python3 -c "print(round(4*($T1-$T0)/3600, 3))")}" >> results/malloc-dd/ledger.jsonl
rm -rf "$TMPDIR" "$GATE_TMP"
echo finished
