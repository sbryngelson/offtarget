#!/bin/bash
# wingtip round 3 (data/evidence/gate_probe/logs/wingtip3.log).
# As run (2026-10-26) from a private copy (~/t48/results/t48/wingtip3/), this
# script's first line was
#   . "$(dirname "$0")/../../maintainers/jobs/wingtip_cap.sh" 2>/dev/null || true
# whose path did not exist there, so these compiles did NOT run inside compliant.slice: they were
# serial compiles (one at a time, nice 10, no GPU use). From the tree the cap is now required.
# wingtip round 3: repeat compiles at fixed paths (is the NVHPC
# post-diagnostic crash a function of the path?), and a fine length sweep
# for the gang-dim program (00).
. "$(cd "$(dirname "$0")/../../.." && pwd)/wingtip_cap.sh" || { echo "cannot source tools/jobs/wingtip_cap.sh" >&2; exit 1; }
ulimit -c 0
R=$(cd "$(dirname "$0")" && pwd)
echo "start $(date -Is) $(hostname)"
one() {  # K NAME
  D=/tmp/${USER}_t48w3/$2; rm -rf $D; mkdir -p $D; cp $R/src/$1/* $D/
  (cd $D && nice -n 10 timeout --kill-after=10 300 bash ./compile.sh > log 2>&1; echo "RC $?" >> log)
  echo "$1 $2 crash=$(grep -c 'TERMINATED by signal' $D/log) $(tail -1 $D/log)"; rm -rf $D
}
for n in 21 29 35 1 3 63; do N=$(printf "%0${n}d" 0 | tr 0 x); for r in 1 2 3 4 5; do one 53 $N; done; done
for n in 1 9 17 37 45; do N=$(printf "%0${n}d" 0 | tr 0 x); for r in 1 2 3; do one 95 $N; done; done
for n in 1 3 33; do N=$(printf "%0${n}d" 0 | tr 0 x); for r in 1 2 3; do one 96 $N; done; done
for n in $(seq 1 1 80); do N=$(printf "%0${n}d" 0 | tr 0 x); one 00 $N; done
echo "end $(date -Is)"; rm -rf /tmp/${USER}_t48w3
