#!/bin/bash
# GCC with OpenMP/OpenACC offloading (gcc.gnu.org/wiki/Offloading): the
# accelerator compiler (with newlib) first, then the host compiler that
# offloads to it, into one prefix. TARGET amdgcn (Tioga, MI250X: device
# libraries for gfx90a and gfx942, assembler and linker from ROCm's LLVM) or
# nvptx (wingtip, A100: nvptx-tools, default -march=sm_80). Release build
# (the release tarball's default --enable-checking=release), no bootstrap
# (the compiler is built once by the host's GCC 13; bootstrapping is a
# self-test of the build, not a different compiler). Languages c, c++,
# fortran, lto. Every input is a verified download (the report says which).
#   Tioga (no pbatch for this account): supervised interactive pdebug runs
#   of at most 60 minutes (the maintainer's limit for Tioga), one at a time,
#   never chained, each named as a compile job; each resumes the last
#   (STEP_LIMIT ends a step before the job's limit):
#     flux run -q pdebug -N1 -n1 -t 60m --job-name=compile-gcc-amdgcn \
#       env TARGET=amdgcn DL=... WORK=/path/to/gcc-work/build \
#       SRCROOT=/tmp/$USER-gcc-src PREFIX=/path/to/gcc-16.2 \
#       STEP_LIMIT=55m JOBS=64 tools/jobs/gcc_offload_build.sh
#   wingtip: TARGET=nvptx (inside the cap: wingtip_cap.sh re-executes it in
#     compliant.slice; each step in a scope of its own, JOBS cores, 64 GB)
#     TARGET=nvptx DL=/path/to/gcc-dl \
#       WORK=/path/to/gcc-build \
#       PREFIX=/path/to/gcc-16.2 JOBS=32 \
#       setsid nohup tools/jobs/gcc_offload_build.sh > LOG 2>&1 < /dev/null &
# Every step runs nice -n 10 under a timeout.
# Status: $WORK/status (one line per step: step rc date). A rerun skips the
# steps the status file records as done.
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
set -u
VER=${GCC_VER:-16.2.0}
NEWLIB=${NEWLIB_VER:-4.6.0.20260123}
TARGET=${TARGET:?TARGET=amdgcn or nvptx}
DL=${DL:?DL=the directory with the verified downloads}
WORK=${WORK:?WORK=the build directory}
PREFIX=${PREFIX:?PREFIX=the install prefix}
JOBS=${JOBS:-32}
HOSTCC=${HOSTCC:-gcc}
HOSTCXX=${HOSTCXX:-g++}
case "$TARGET" in
  amdgcn) ACCEL=amdgcn-amdhsa
          LLVM=${LLVM:-/opt/rocm-7.2.1/llvm}
          ACCEL_OPTS="--with-multilib-list=${GCN_ARCHES:-gfx90a,gfx942} --disable-libquadmath" ;;
  nvptx) ACCEL=nvptx-none
         CUDA=${CUDA:-/usr/local/cuda}
         ACCEL_OPTS="--with-arch=${NVPTX_ARCH:-sm_80} --enable-newlib-io-long-long" ;;
  *) echo "TARGET must be amdgcn or nvptx"; exit 2 ;;
esac
HOST=x86_64-pc-linux-gnu
# every configure uses the host's GCC (wingtip's login environment sets CC
# to NVHPC's nvc)
export CC=$HOSTCC CXX=$HOSTCXX
unset CFLAGS CXXFLAGS LDFLAGS CPPFLAGS FC F77 F90 LD_LIBRARY_PATH
mkdir -p "$WORK" "$PREFIX" || exit 1
ST=$WORK/status
touch "$ST"
# the sources may live apart from the build (Tioga: unpacked again in each
# session into the node's /tmp at the same path; the build directories and
# the install stay on /p/vast1, so a session that ends resumes in the next)
SRCROOT=${SRCROOT:-$WORK}
SRC=$SRCROOT/gcc-$VER
LIMIT=${STEP_LIMIT:-3h}

step() {  # step NAME LIMIT CMD...: bounded, niced; skipped when done
  local name=$1 limit=$2; shift 2
  if grep -q "^$name 0 " "$ST"; then echo "== $name: done before"; return 0; fi
  echo "== $name start $(date -Is)"
  local scope=()
  # wingtip: each step in its own scope of the slice, at most JOBS cores
  # and 64 GB (a GCC compile job takes about 1 GB)
  [ -n "${COMPLIANT_CAPPED:-}" ] && scope=(systemd-run --user
    --slice=compliant.slice --scope --quiet -p CPUQuota=$((JOBS * 100))%
    -p MemoryHigh=48G -p MemoryMax=64G)
  "${scope[@]}" nice -n 10 timeout --kill-after=60 "$limit" "$@"
  local rc=$?
  echo "$name $rc $(date -Is)" >> "$ST"
  echo "== $name rc=$rc $(date -Is)"
  return $rc
}

unpack() {
  mkdir -p "$SRCROOT" && cd "$SRCROOT" || return 1
  rm -rf "gcc-$VER" "newlib-$NEWLIB"
  tar xf "$DL/gcc-$VER.tar.xz" || return 1
  tar xf "$DL/newlib-$NEWLIB.tar.gz" || return 1
  ln -s "../newlib-$NEWLIB/newlib" "$SRC/newlib" || return 1
  # the prerequisites, as contrib/download_prerequisites links them
  local p
  for p in gmp-6.3.0.tar.bz2 mpfr-4.2.2.tar.bz2 mpc-1.3.1.tar.gz isl-0.24.tar.bz2; do
    tar xf "$DL/prereq/$p" -C "$SRC" || return 1
    local d=${p%.tar.*}
    ln -s "$d" "$SRC/${d%-*}" || return 1
  done
}

tools_amdgcn() {  # LLVM's assembler and linker (copied: no tie to ROCm)
  local b=$PREFIX/$ACCEL/bin
  mkdir -p "$b" "$PREFIX/bin" || return 1
  cp -L "$LLVM/bin/llvm-mc" "$b/as" && cp -L "$LLVM/bin/lld" "$b/ld" &&
    cp -L "$LLVM/bin/llvm-nm" "$b/nm" &&
    cp -L "$LLVM/bin/llvm-objdump" "$b/objdump" &&
    cp -L "$LLVM/bin/llvm-ar" "$b/ar" && cp -L "$LLVM/bin/llvm-ar" "$b/ranlib" &&
    cp -L "$LLVM/bin/llvm-ar" "$PREFIX/bin/$ACCEL-ar" &&
    cp -L "$LLVM/bin/llvm-ar" "$PREFIX/bin/$ACCEL-ranlib" &&
    "$LLVM/bin/llvm-mc" --version > "$PREFIX/$ACCEL/llvm-tools-version.txt"
}

tools_nvptx() {  # nvptx-tools (as, ld, nm, run); nvptx-as verifies its
  # output with CUDA's NVRTC/ptxas when PATH/LD_LIBRARY_PATH find them
  rm -rf "$WORK/nvptx-tools" && cp -r "$DL/nvptx-tools" "$WORK/" &&
    cd "$WORK/nvptx-tools" &&
    ./configure --prefix="$PREFIX" &&
    make -j "$JOBS" && make install
}

accel() {
  mkdir -p "$WORK/build-$TARGET" && cd "$WORK/build-$TARGET" || return 1
  [ -f Makefile ] || CC=$HOSTCC CXX=$HOSTCXX "$SRC/configure" \
    --target=$ACCEL --enable-as-accelerator-for=$HOST \
    --with-build-time-tools="$PREFIX/$ACCEL/bin" \
    --enable-languages=c,c++,fortran,lto --with-newlib \
    --disable-sjlj-exceptions $ACCEL_OPTS \
    --prefix="$PREFIX" || return 1
  make -j "$JOBS" && make install
}

host() {
  mkdir -p "$WORK/build-host" && cd "$WORK/build-host" || return 1
  [ -f Makefile ] || CC=$HOSTCC CXX=$HOSTCXX "$SRC/configure" \
    --build=$HOST --host=$HOST --target=$HOST \
    --enable-offload-targets=$ACCEL="$PREFIX/$ACCEL" \
    --enable-offload-defaulted \
    --enable-languages=c,c++,fortran,lto \
    --disable-multilib --disable-bootstrap \
    --prefix="$PREFIX" || return 1
  make -j "$JOBS" && make install
}

echo "host $(hostname) $(date -Is) TARGET=$TARGET PREFIX=$PREFIX JOBS=$JOBS"
"$HOSTCC" --version | head -1
if [ ! -f "$SRC/.unpacked" ]; then
  echo "== unpack $(date -Is)"
  nice -n 10 timeout 30m bash -c "$(declare -f unpack); SRCROOT=$SRCROOT VER=$VER NEWLIB=$NEWLIB DL=$DL SRC=$SRC unpack" &&
    touch "$SRC/.unpacked" || exit 1
fi
step tools 30m bash -c "$(declare -f tools_$TARGET); PREFIX=$PREFIX ACCEL=$ACCEL LLVM=${LLVM:-} CUDA=${CUDA:-} WORK=$WORK DL=$DL JOBS=$JOBS tools_$TARGET" || exit 1
export PATH=$PREFIX/bin:$PATH
[ "$TARGET" = nvptx ] && export PATH=$PATH:$CUDA/bin \
  LD_LIBRARY_PATH=${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}$CUDA/lib64
step accel $LIMIT bash -c "$(declare -f accel); WORK=$WORK TARGET=$TARGET SRC=$SRC ACCEL=$ACCEL HOST=$HOST PREFIX=$PREFIX HOSTCC=$HOSTCC HOSTCXX=$HOSTCXX JOBS=$JOBS ACCEL_OPTS='$ACCEL_OPTS' accel" || exit 1
step host $LIMIT bash -c "$(declare -f host); WORK=$WORK SRC=$SRC ACCEL=$ACCEL HOST=$HOST PREFIX=$PREFIX HOSTCC=$HOSTCC HOSTCXX=$HOSTCXX JOBS=$JOBS host" || exit 1
"$PREFIX/bin/gcc" --version | head -1
"$PREFIX/bin/gcc" -v 2>&1 | grep -E "^Configured with|OFFLOAD_TARGET"
echo "done $(date -Is)" >> "$ST"
