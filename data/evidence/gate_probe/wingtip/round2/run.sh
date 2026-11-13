#!/bin/bash
# wingtip round 2 (data/evidence/gate_probe/logs/wingtip2.log).
# As run (2026-10-26) from a private copy (~/t48/results/t48/wingtip2/), this
# script's first line was
#   . "$(dirname "$0")/../../maintainers/jobs/wingtip_cap.sh" 2>/dev/null || true
# whose path did not exist there, so these compiles did NOT run inside compliant.slice: they were
# serial compiles (one at a time, nice 10, no GPU use). From the tree the cap is now required.
. "$(cd "$(dirname "$0")/../../.." && pwd)/wingtip_cap.sh" || { echo "cannot source tools/jobs/wingtip_cap.sh" >&2; exit 1; }
ulimit -c 0
R=$(cd "$(dirname "$0")" && pwd)
echo "start $(date -Is) $(hostname)"
for n in $(seq 1 2 64); do N=$(printf "%0${n}d" 0 | tr 0 x); D=/tmp/${USER}_t48w/$N; rm -rf $D; mkdir -p $D; cp $R/src/00/* $D/; (cd $D && nice -n 10 timeout --kill-after=10 300 bash ./compile.sh > log 2>&1; echo "RC $?" >> log); echo "00 len$n crash=$(grep -c "TERMINATED by signal" $D/log) $(tail -1 $D/log) $(grep -c "S-0" $D/log)"; rm -rf $D; done
for n in $(seq 1 2 64); do N=$(printf "%0${n}d" 0 | tr 0 x); D=/tmp/${USER}_t48w/$N; rm -rf $D; mkdir -p $D; cp $R/src/53/* $D/; (cd $D && nice -n 10 timeout --kill-after=10 300 bash ./compile.sh > log 2>&1; echo "RC $?" >> log); echo "53 len$n crash=$(grep -c "TERMINATED by signal" $D/log) $(tail -1 $D/log) $(grep -c "S-0" $D/log)"; rm -rf $D; done
for n in $(seq 1 2 64); do N=$(printf "%0${n}d" 0 | tr 0 x); D=/tmp/${USER}_t48w/$N; rm -rf $D; mkdir -p $D; cp $R/src/95/* $D/; (cd $D && nice -n 10 timeout --kill-after=10 300 bash ./compile.sh > log 2>&1; echo "RC $?" >> log); echo "95 len$n crash=$(grep -c "TERMINATED by signal" $D/log) $(tail -1 $D/log) $(grep -c "S-0" $D/log)"; rm -rf $D; done
for n in $(seq 1 2 64); do N=$(printf "%0${n}d" 0 | tr 0 x); D=/tmp/${USER}_t48w/$N; rm -rf $D; mkdir -p $D; cp $R/src/96/* $D/; (cd $D && nice -n 10 timeout --kill-after=10 300 bash ./compile.sh > log 2>&1; echo "RC $?" >> log); echo "96 len$n crash=$(grep -c "TERMINATED by signal" $D/log) $(tail -1 $D/log) $(grep -c "S-0" $D/log)"; rm -rf $D; done
echo "end $(date -Is)"; rm -rf /tmp/${USER}_t48w
