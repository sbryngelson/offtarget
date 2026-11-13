#!/bin/bash
# The OpenACC atomic update x = x + e1 + e2 (legal, 3.4 §2.12) on NVHPC
# 25.11 and 26.9 (wingtip, A100): C (nvc) and Fortran (nvfortran) forms, -O0/-O2, -acc=gpu and
# -acc=multicore; the parenthesised and compound forms as controls; every binary that links is
# run once on a free GPU (the project's per-GPU run lock), each step under timeout.
#   cd data/evidence/acc_c_probe/atomic && bash run.sh > run.log 2>&1
#
. "$(dirname "$0")/../../wingtip_cap.sh" || exit 1
cd "$(dirname "$0")"
ulimit -c 0
G=${GPU:-3}
echo "host $(hostname) $(date -Is) GPU $G"
for R in /opt/nvidia/hpc_sdk/Linux_x86_64/25.11 <site>/nvhpc/Linux_x86_64/26.9; do
  export LD_LIBRARY_PATH=$R/compilers/lib
  for f in sum.c sum_paren.c sum_compound.c sum.f90 sum_paren.f90 gang.f90 gang_paren.f90; do
    case $f in *.c) cc=$R/compilers/bin/nvc ;; *) cc=$R/compilers/bin/nvfortran ;; esac
    for fl in "-O2 -acc=gpu -gpu=cc80 -gpu=mem:separate" "-O0 -acc=gpu -gpu=cc80 -gpu=mem:separate" "-O2 -acc=multicore"; do
      echo; echo "== $(basename $R) $f [$fl]"
      rm -f p.out
      timeout --kill-after=10 120 $cc $fl $f -o p.out 2>&1; echo "compile exit $?"
      if [ -x p.out ]; then
        flock /tmp/compliant-run-$(id -u)-gpu$G.lock env CUDA_VISIBLE_DEVICES=$G timeout --kill-after=10 60 ./p.out 2>&1
        echo "run exit $?"
      fi
    done
  done
  $R/compilers/bin/nvc --version | sed -n 2p
done
rm -f p.out *.mod
