#!/bin/bash
# wingtip round 1 (data/evidence/gate_probe/logs/wingtip1.log).
# As run (2026-10-26) from a private copy (~/t48/results/t48/wingtip/), this
# script's first line was
#   . "$(dirname "$0")/../../maintainers/jobs/wingtip_cap.sh" 2>/dev/null || true
# whose path did not exist there, so these compiles did NOT run inside compliant.slice: they were
# serial compiles (one at a time, nice 10, no GPU use). From the tree the cap is now required.
. "$(cd "$(dirname "$0")/../../.." && pwd)/wingtip_cap.sh" || { echo "cannot source tools/jobs/wingtip_cap.sh" >&2; exit 1; }
ulimit -c 0
R=$(cd "$(dirname "$0")" && pwd)
T=/tmp/${USER}_t48wt; mkdir -p $T
echo "start $(date -Is) $(hostname)"
for i in $(seq 1 20); do for P in A_$i GATEXQ$i; do D=$T/00_$P; rm -rf $D; mkdir -p $D; cp $R/src/00/* $D/; (cd $D && nice -n 10 timeout --kill-after=10 300 bash ./compile.sh > log 2>&1; echo "RC $?" >> log); echo "00 $P $(grep -c "TERMINATED by signal" $D/log) $(tail -1 $D/log) $(grep -m1 -o "S-[0-9]*-[^(]*" $D/log)"; rm -rf $D; done; done
for i in $(seq 1 20); do for P in A_$i GATEXQ$i; do D=$T/53_$P; rm -rf $D; mkdir -p $D; cp $R/src/53/* $D/; (cd $D && nice -n 10 timeout --kill-after=10 300 bash ./compile.sh > log 2>&1; echo "RC $?" >> log); echo "53 $P $(grep -c "TERMINATED by signal" $D/log) $(tail -1 $D/log) $(grep -m1 -o "S-[0-9]*-[^(]*" $D/log)"; rm -rf $D; done; done
for i in $(seq 1 20); do for P in A_$i GATEXQ$i; do D=$T/95_$P; rm -rf $D; mkdir -p $D; cp $R/src/95/* $D/; (cd $D && nice -n 10 timeout --kill-after=10 300 bash ./compile.sh > log 2>&1; echo "RC $?" >> log); echo "95 $P $(grep -c "TERMINATED by signal" $D/log) $(tail -1 $D/log) $(grep -m1 -o "S-[0-9]*-[^(]*" $D/log)"; rm -rf $D; done; done
for i in $(seq 1 20); do for P in A_$i GATEXQ$i; do D=$T/96_$P; rm -rf $D; mkdir -p $D; cp $R/src/96/* $D/; (cd $D && nice -n 10 timeout --kill-after=10 300 bash ./compile.sh > log 2>&1; echo "RC $?" >> log); echo "96 $P $(grep -c "TERMINATED by signal" $D/log) $(tail -1 $D/log) $(grep -m1 -o "S-[0-9]*-[^(]*" $D/log)"; rm -rf $D; done; done
echo "end $(date -Is)"; rm -rf $T
