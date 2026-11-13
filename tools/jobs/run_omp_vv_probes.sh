#!/bin/bash
# NOTE: predates the pinned CCE preludes of offload/engine/toolchains.py (rocm/<version>, module unload cray-mpich); its module lines are the ones.
# The two open omp_vv cross-check items, run on the compute node
# (inside the allocation of tools/jobs/run_copy_subset.sh). Small programs in
# data/evidence/omp_vv_probe (ours) and copies of three omp_vv tests, compiled
# with each toolchain's fixed flags and run at HSA_XNACK=1 and 0 with
# OMP_TARGET_OFFLOAD=mandatory. Non-strict on purpose.
ulimit -c 0
ROOT=${COMPLIANT_ROOT:-$PWD}
P=$ROOT/data/evidence/omp_vv_probe
C=$ROOT/corpus/omp_vv
AFAR=${AFAR_ROOT:-$(cd "$ROOT" && python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import TOOLCHAINS as T; print(T["afar"].install_root)')}/bin
W=$(mktemp -d /tmp/${USER:-user}-probe-XXXXXX)
cp $P/*.f90 $W/
cp -r $C/ompvv $W/ompvv
cp $C/tests/5.1/target/test_target_map_iterators.F90 \
   $C/tests/5.0/target_simd/test_target_simd_order_concurrent.F90 \
   $C/tests/5.0/loop/test_loop_order_concurrent_device.F90 $W/
cd $W
for tc in afar cce19; do
  (
  if [ $tc = cce19 ]; then
    . /etc/profile >/dev/null 2>&1
    module load cce/19.0.0 craype-accel-amd-gfx942 rocm
    FC="ftn -fopenmp -O2"
  else
    FC="$AFAR/amdflang -fopenmp --offload-arch=gfx942 -L/usr/lib/gcc/x86_64-redhat-linux/8 -O2"
  fi
  for src in ord_do.f90 ord_simd.f90 ord_loop.f90 ord_tsimd.f90 iter_target.f90 iter_enter.f90 \
             test_target_map_iterators.F90 test_target_simd_order_concurrent.F90 \
             test_loop_order_concurrent_device.F90; do
    exe=$tc.${src%.*}.x
    echo "=== $tc $src: compile"
    $FC -I./ompvv $src -o $exe > $exe.log 2>&1
    rc=$?
    echo "compile rc=$rc"; grep -i -E "error|not yet|undefined" $exe.log | head -5
    [ $rc = 0 ] || continue
    for x in 1 0; do
      out=$(HSA_XNACK=$x OMP_TARGET_OFFLOAD=mandatory timeout 120 ./$exe 2>&1)
      echo "--- $tc $src HSA_XNACK=$x rc=$?"
      echo "$out" | tail -6
    done
  done
  )
done
cd /; rm -rf $W
