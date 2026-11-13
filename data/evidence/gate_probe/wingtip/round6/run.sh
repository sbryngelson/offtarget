#!/bin/bash
# Wingtip round 6: NVHPC 25.11 and 26.9 (separate memory)
# as the other family for the integer(8) OpenACC reduction and the 63-scalar C
# reduction (data/evidence/gate_probe/reduce/): compile and run each twice on ONE
# free GPU, one program at a time under the per-GPU run lock (flock on the
# harness's lock file), nice, every step under timeout.
. "$(cd "$(dirname "$0")/../../.." && pwd)/wingtip_cap.sh" || { echo "cannot source tools/jobs/wingtip_cap.sh" >&2; exit 1; }
ulimit -c 0
R=$(cd "$(dirname "$0")" && pwd)
G=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | awk -F', ' '$2 < 100 {print $1; exit}')
[ -n "$G" ] || { echo "no free GPU: stop"; exit 3; }
export CUDA_VISIBLE_DEVICES=$G
LOCK=/tmp/compliant-run-$(id -u)-gpu$G.lock
T=/tmp/${USER}_t48w6; rm -rf $T; mkdir -p $T
echo "start $(date -Is) $(hostname) gpu $G"
for rel in 25.11 26.9; do
  case $rel in
    25.11) B=/opt/nvidia/hpc_sdk/Linux_x86_64/25.11/compilers;;
    26.9) B=<site>/nvhpc/Linux_x86_64/26.9/compilers;;
  esac
  for f in $(ls $R/src); do
    case $f in
      *.c) CMD="$B/bin/nvc -mp=gpu -gpu=cc80 -gpu=mem:separate -O2";;
      red_acc_*) CMD="$B/bin/nvfortran -acc=gpu -gpu=cc80 -gpu=mem:separate -O2";;
      *) CMD="$B/bin/nvfortran -mp=gpu -gpu=cc80 -gpu=mem:separate -O2";;
    esac
    D=$T/$rel.${f%.*}; mkdir -p $D; cp $R/src/$f $D/
    (cd $D && nice -n 10 timeout --kill-after=10 600 $CMD $f -o prog.out > build.log 2>&1)
    rc=$?
    if [ $rc -ne 0 ]; then echo "$rel $f compile rc=$rc $(grep -m1 -E 'S-|F-|rror' $D/build.log)"; continue; fi
    for k in 1 2; do
      (cd $D && flock $LOCK env LD_LIBRARY_PATH=$B/lib OMP_TARGET_OFFLOAD=mandatory nice -n 10 timeout --kill-after=10 600 ./prog.out > run.log 2>&1)
      rc=$?
      echo "$rel $f run$k rc=$rc $(tail -3 $D/run.log | tr '\n' ' ')"
    done
  done
done
echo "end $(date -Is)"; rm -rf $T
