#!/bin/bash
# build the amdgcn libc from the exact AFAR commit, one variant per argument (ctl rel relacq)
W=<site>/compliant/results/student-repro/libc-build
AV=<site>/afar/therock-afar-24.3.0-multiarch-10.1.0-592954c
CC=$AV/lib/llvm/bin/clang; CXX=$AV/lib/llvm/bin/clang++
build_one() { v=$1
  B=$W/build-$v; rm -rf $B
  cmake -G "Unix Makefiles" -S $W/src-$v/runtimes -B $B \
    -DLLVM_ENABLE_RUNTIMES=libc -DCMAKE_C_COMPILER=$CC -DCMAKE_CXX_COMPILER=$CXX \
    -DLLVM_LIBC_FULL_BUILD=ON -DLLVM_DEFAULT_TARGET_TRIPLE=amdgcn-amd-amdhsa \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_AR=$AV/lib/llvm/bin/llvm-ar -DCMAKE_RANLIB=$AV/lib/llvm/bin/llvm-ranlib \
    -DLIBC_TARGET_TRIPLE=amdgcn-amd-amdhsa -DCMAKE_C_COMPILER_TARGET=amdgcn-amd-amdhsa -DCMAKE_CXX_COMPILER_TARGET=amdgcn-amd-amdhsa -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY -DLIBC_GPU_ARCHITECTURES=gfx942 > $W/cfg-$v.log 2>&1 || { echo "configure $v failed"; tail -15 $W/cfg-$v.log; return 1; }
  make -C $B -j 30 libc > $W/make-$v.log 2>&1 && echo "built $v" || { echo "build $v failed"; tail -20 $W/make-$v.log; }
  find $B -name libc.a | head -2
}
for v in "$@"; do build_one $v & done; wait
