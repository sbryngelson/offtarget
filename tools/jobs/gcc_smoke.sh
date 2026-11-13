#!/bin/bash
# Smoke test of GCC's OpenMP/OpenACC offload (tests/data/gcc_smoke): C and
# Fortran target programs compiled with the toolchain's flags and run under
# OMP_TARGET_OFFLOAD=mandatory with GOMP_DEBUG=1 (nvptx) or GCN_DEBUG=1
# (GCN): libgomp's plugin reports each kernel launch (device execution);
# OpenACC (-fopenacc) in both
# languages; libm in a target region; what `requires unified_shared_memory`
# does in each memory setting (memory modes are measured, not assumed).
#   Tioga (inside a bounded interactive flux run on a compute node):
#     TARGET=amdgcn tools/jobs/gcc_smoke.sh OUTDIR
#   wingtip (inside the cap, one free GPU under its run lock):
#     TARGET=nvptx tools/jobs/gcc_smoke.sh OUTDIR [GPU]
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
set -u
ulimit -c 0
SRC=$(cd "$(dirname "$0")/../../tests/data/gcc_smoke" && pwd)
OUT=${1:?usage: $0 OUTDIR [GPU]}
TARGET=${TARGET:?TARGET=amdgcn or nvptx}
mkdir -p "$OUT" && cd "$OUT" || exit 1
unset CC CXX FC LD_LIBRARY_PATH OMP_TARGET_OFFLOAD HSA_XNACK
case "$TARGET" in
  amdgcn)
    ROOT=${GCC_ROOT:-$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import TOOLCHAINS as T; print(T["gcc_g90"].install_root)')}
    ARCH=${ARCH:-gfx90a}
    ROCM=${ROCM:-/opt/rocm-7.2.1}
    OFF="-foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=$ARCH"
    export LD_LIBRARY_PATH=$ROOT/lib64:$ROCM/lib
    MODES="0 unset 1"
    LOCK=/dev/null
    "$ROCM/bin/rocminfo" | grep -m2 -E "^\s+Name:\s+gfx" ;;
  nvptx)
    ROOT=${GCC_ROOT:-$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import TOOLCHAINS as T; print(T["gcc_sm80"].install_root)')}
    ARCH=${ARCH:-sm_80}
    OFF="-foffload=nvptx-none -foffload-options=nvptx-none=-march=$ARCH -foffload-options=nvptx-none=-latomic"
    export LD_LIBRARY_PATH=$ROOT/lib64 PATH=/usr/local/cuda/bin:$PATH
    MODES="0"
    G=${2:-$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits |
             awk -F', ' '$2 < 100 {print $1; exit}')}
    [ -n "$G" ] || { echo "no free GPU"; exit 3; }
    export CUDA_VISIBLE_DEVICES=$G
    LOCK=${TMPDIR:-/tmp}/compliant-run-$(id -u)-gpu$G.lock
    echo "GPU $G" ;;
  *) echo "TARGET must be amdgcn or nvptx"; exit 2 ;;
esac
echo "host $(hostname) $(date -Is) root $ROOT arch $ARCH"
"$ROOT/bin/gcc" --version | head -1
"$ROOT/bin/gfortran" --version | head -1
run() {  # name mode(HSA_XNACK value | unset) compiler flags...
  local name=$1 mode=$2; shift 2
  echo "=== $name [$mode]: $*"
  if [ ! -x "$name.out" ]; then
    nice -n 10 timeout --kill-after=10 300 "$@" -o "$name.out" > "$name.compile.log" 2>&1
    echo "compile rc=$?"; tail -8 "$name.compile.log"
  fi
  [ -x "$name.out" ] || return
  local x=()
  [ "$TARGET" = amdgcn ] && [ "$mode" != unset ] && x=(HSA_XNACK=$mode)
  for off in mandatory unset; do
    local o=(OMP_TARGET_OFFLOAD=$off)
    [ "$off" = unset ] && o=()
    env "${x[@]}" "${o[@]}" GOMP_DEBUG=1 GCN_DEBUG=1 flock "$LOCK" nice -n 10 \
      timeout --kill-after=10 120 "./$name.out" > "$name.$mode.$off.log" 2>&1
    echo "run [$off] rc=$?: $(grep -E 'PASS|FAIL' "$name.$mode.$off.log" | head -2)"
    grep -m2 -i -E "launch|libgomp:" "$name.$mode.$off.log"
  done
}
for m in $MODES; do
  run teams_c "$m" "$ROOT/bin/gcc" -fopenmp $OFF -O2 "$SRC/teams.c"
done
run data_c 0 "$ROOT/bin/gcc" -fopenmp $OFF -O2 "$SRC/data.c"
run teams_f 0 "$ROOT/bin/gfortran" -fopenmp $OFF -O2 "$SRC/teams.f90"
run data_f 0 "$ROOT/bin/gfortran" -fopenmp $OFF -O2 "$SRC/data.f90"
run math_c 0 "$ROOT/bin/gcc" -fopenmp $OFF -O2 "$SRC/math.c" -lm
run acc_f 0 "$ROOT/bin/gfortran" -fopenacc $OFF -O2 "$SRC/acc.f90"
run acc_c 0 "$ROOT/bin/gcc" -fopenacc $OFF -O2 "$SRC/acc.c"
for m in $MODES; do
  run usm_c "$m" "$ROOT/bin/gcc" -fopenmp $OFF -O2 "$SRC/usm.c"
done
echo "=== offload targets of the driver"
"$ROOT/bin/gcc" -v 2>&1 | grep -E "OFFLOAD_TARGET|^Configured"
echo "=== _OPENMP, _OPENACC"
echo | "$ROOT/bin/gcc" -fopenmp -fopenacc -dM -E - | grep -E "_OPENMP|_OPENACC"
echo "done $(date -Is)"
