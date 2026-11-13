#!/bin/bash
# sweep K: compile probe/stress.f90 as stress.f90 in /tmp/cce-cif/<K a>-1aa with CCE 19 (-fopenmp -O2 -c)
. /etc/profile >/dev/null 2>&1
module load cce/19.0.0 craype-accel-amd-gfx942 rocm/6.4.3 >/dev/null 2>&1; module unload cray-mpich >/dev/null 2>&1
SRC=<site>/compliant/vendor/checks/probe/stress.f90
one() {
  K=$1; D=/tmp/cce-cif/$(printf 'a%.0s' $(seq 1 $K))-1aa
  rm -rf $D; mkdir -p $D; cp $SRC $D/stress.f90
  ( cd $D && timeout --kill-after=10 120 ftn -fopenmp -O2 -c stress.f90 > log 2>&1; echo "K=$K rc=$? msgs=$(grep -c '^ftn-' log) $(grep -m1 -o 'free().*' log)" )
  rm -rf $D
}
export -f one; export SRC
seq ${1:-150} ${2:-260} | xargs -P 24 -I{} bash -c 'one {}' | sort -t= -k2 -n
