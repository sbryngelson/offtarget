#!/bin/bash
# wingtip round 4 (data/evidence/gate_probe/logs/wingtip4.log).
# As run (2026-10-26) from a private copy (~/t48/results/t48/wingtip4/), this
# script's first line was
#   . "$(dirname "$0")/../../maintainers/jobs/wingtip_cap.sh" 2>/dev/null || true
# whose path did not exist there, so these compiles did NOT run inside compliant.slice: they were
# serial compiles (one at a time, nice 10, no GPU use). From the tree the cap is now required.
# wingtip round 4: the nvcpfe crash after the ordered diagnostic
# (data/findings/nvhpc-c-ordered-in-target-nvcpfe-crash.c): the program at
# a long and a short source path on both releases and memory modes, and a
# host-only control.
. "$(cd "$(dirname "$0")/../../.." && pwd)/wingtip_cap.sh" || { echo "cannot source tools/jobs/wingtip_cap.sh" >&2; exit 1; }
ulimit -c 0
R=$(cd "$(dirname "$0")" && pwd)
echo "start $(date -Is) $(hostname)"
for rel in 25.11 26.9; do
  case $rel in 25.11) NVC=/opt/nvidia/hpc_sdk/Linux_x86_64/25.11/compilers/bin/nvc;; 26.9) NVC=<site>/nvhpc/Linux_x86_64/26.9/compilers/bin/nvc;; esac
  for mem in separate managed; do
    for N in x xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx; do
      for r in 1 2 3; do
        D=/tmp/${USER}_t48w4/$N; rm -rf $D; mkdir -p $D; cp $R/src/repro.c $D/omp52-c-w-ordered.c
        (cd $D && nice -n 10 timeout --kill-after=10 300 $NVC -mp=gpu -gpu=cc80 -gpu=mem:$mem -O2 $D/omp52-c-w-ordered.c -o prog.out > log 2>&1; echo "RC $?" >> log)
        echo "repro $rel $mem pathlen=$(( ${#D} + 20 )) crash=$(grep -c 'TERMINATED by signal' $D/log) $(tail -1 $D/log) | $(grep -m1 -o 'S-0155-[^(]*' $D/log)"
      done
    done
    D=/tmp/${USER}_t48w4/ctl; rm -rf $D; mkdir -p $D; cp $R/src/control_host.c $D/
    (cd $D && nice -n 10 timeout --kill-after=10 300 $NVC -mp=gpu -gpu=cc80 -gpu=mem:$mem -O2 $D/control_host.c -o prog.out > log 2>&1; echo "RC $?" >> log; ./prog.out >> log 2>&1)
    echo "control $rel $mem $(tr '\n' ' ' < $D/log)"
  done
done
echo "end $(date -Is)"; rm -rf /tmp/${USER}_t48w4
