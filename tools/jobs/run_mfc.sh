#!/bin/bash
# MFC (data/bench/apps/manifest.yaml, app mfc) built by its own build
# system and checked by its own test suite (golden files), per toolchain
# and GPU model, on this machine. One working copy per toolchain and model:
# results/apps/mfc/<toolchain>-<gpu>/MFC (a copy of corpus/apps/MFC with its
# Python environment), so builds never share a staging directory.
#   tools/jobs/run_mfc.sh build <toolchain> <mp|acc>        # pre_process + simulation
#   tools/jobs/run_mfc.sh test  <toolchain> <mp|acc> <mode> # the data/bench/apps/mfc_tests.txt subset
#   tools/jobs/run_mfc.sh rerun <toolchain> <mp|acc> <mode> UUID... # those tests alone, one at a
#     time, into test.<mode>.rerun.log (a timeout the host's load may have caused;
#     offload.engine.apps.mfc_records replaces only a first-run timeout with the rerun's outcome).
#     On wingtip (NVHPC): in the capped compliant.slice (tools/jobs/wingtip_cap.sh), on
#     one GPU no other user's process holds (RERUN_GPU, default the first free one), under that
#     GPU's run lock (/tmp/compliant-run-<uid>-gpu<N>.lock, the harness's), nice, and a timeout
#     (RERUN_TIMEOUT s, default 3600).
# Tuolumne: flux batch -q pbatch -N1 -t 60 --setattr=thp=always \
#   --output=results/apps/mfc.%j.log tools/jobs/run_mfc.sh build afar mp
# Modes: unified (HSA_XNACK=1), copy (HSA_XNACK=0) on the AMD machine;
# NVHPC: copy (-gpu=mem:separate, the default) only: the mode is a compile
# flag MFC's build does not take, so managed is not run.
# on wingtip every step runs in the capped user slice (docs/tooling/wingtip.md; a no-op elsewhere)
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
ulimit -c 0
ROOT=${COMPLIANT_ROOT:-$PWD}
STEP=$1; TC=$2; GPU=$3; MODE=${4:-}
shift 4 2>/dev/null || shift $#
RERUN="$*"
# MFC_VARIANT: a separate working copy (<tc>-<gpu>-<variant>, not a corpus record) with a
# workaround for the CCE 20/21 device-link crashes (data/findings/apps/): nolines (fypp without
# --line-numbering, cmake/Fypp.cmake), o0cbc (m_compute_cbc compiled at -O0)
VARIANT=${MFC_VARIANT:-}
W=$ROOT/results/apps/mfc/$TC-$GPU${VARIANT:+-$VARIANT}
mkdir -p "$W"
echo "host $(hostname) git $(git -C "$ROOT" rev-parse --short HEAD) start $(date -Is) $*"
if [ ! -d "$W/MFC" ]; then
  rsync -a --exclude build/staging --exclude build/install --exclude 'build/lock*' \
    "$ROOT/corpus/apps/MFC/" "$W/MFC/"
fi
cd "$W/MFC"
# MFC builds its syscheck program (a GPU sanity check, not part of the
# solver) before every target; CCE 21's C++ runtime link fails for it on
# Tuolumne (libstdc++_nonshared: undefined _Unwind_Resume), which would stop
# the build of the solver itself: the corpus does not require it
sed -i 's/^SYSCHECK = MFCTarget("syscheck", \["-DMFC_SYSCHECK=ON"\], False, False, True,/SYSCHECK = MFCTarget("syscheck", ["-DMFC_SYSCHECK=ON"], False, False, False,/' toolchain/mfc/build.py
if [ "$VARIANT" = nolines ]; then
  sed -i '/--line-numbering/d' cmake/Fypp.cmake
elif [ "$VARIANT" = o0cbc ]; then
  # CCE 20 workaround (data/findings/apps/cce20-device-link-infer-address-spaces-crash.f90):
  # m_compute_cbc at -O0
  grep -q "^# O0cbc: CCE 20 device-link crash" CMakeLists.txt || cat >> CMakeLists.txt <<'CMK'
# O0cbc: CCE 20 device-link crash (Infer address spaces) avoided with m_compute_cbc at -O0
if (MFC_SIMULATION AND CMAKE_Fortran_COMPILER_ID STREQUAL "Cray")
    set_source_files_properties("${CMAKE_BINARY_DIR}/fypp/simulation/m_compute_cbc.fpp.f90"
                                PROPERTIES COMPILE_OPTIONS "-O0")
endif()
CMK
elif [ -n "$VARIANT" ]; then
  echo "unknown MFC_VARIANT $VARIANT"; exit 2
fi
# the test suite aborts once 30% of its tests fail ("a systemic issue"):
# the corpus records every test's outcome, so it never aborts
# NVHPC 26.9 ships no libnvhpcwrapnvtx (25.11 does), which MFC links for
# its NVTX ranges when CUDA >= 12.9; -cudalib=nvtx3 stays
if [ "$TC" = nvhpc269 ]; then
  sed -i 's/^\( *\)target_link_libraries(${a_target} PRIVATE nvhpcwrapnvtx)/\1# (not in NVHPC 26.9) nvhpcwrapnvtx/' cmake/MFCTargets.cmake
  [ "$STEP" = build ] && rm -rf build/staging build/install
fi
sed -i 's/^FAILURE_RATE_THRESHOLD = 0.3$/FAILURE_RATE_THRESHOLD = 1.01/' toolchain/mfc/test/test.py
# a hung test is a failure after 5 minutes, not an hour (MFC's default)
sed -i 's/^TEST_TIMEOUT_SECONDS = .*/TEST_TIMEOUT_SECONDS = 300/' toolchain/mfc/test/test.py
AFAR_ROOT=${AFAR_ROOT:-$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import TOOLCHAINS as T; print(T["afar"].install_root)')}
case $TC in
  afar)
    export FC=$AFAR_ROOT/bin/amdflang CC=$AFAR_ROOT/bin/amdclang CXX=$AFAR_ROOT/bin/amdclang++
    export OLCF_AFAR_ROOT=$AFAR_ROOT MFC_AMD_GPU_ARCH=gfx942
    # amdflang picks the newest gcc-toolset, which lacks libquadmath.so
    # (MFC's toolchain/modules, tamd): use 14's
    export LIBRARY_PATH=/opt/rh/gcc-toolset-14/root/usr/lib/gcc/x86_64-redhat-linux/14:${LIBRARY_PATH:-}
    export LD_LIBRARY_PATH=$AFAR_ROOT/lib:$AFAR_ROOT/lib/llvm/lib:${LD_LIBRARY_PATH:-}
    ;;
  cce19|cce20|cce21)
    v=$(python3 -I -c "import sys; sys.path.insert(0,'$ROOT'); from offload.engine.toolchains import TOOLCHAINS as T; import re; print(re.search(r'cce/(\S+)', T['$TC'].prelude).group(1), re.search(r'rocm/(\S+)', T['$TC'].prelude).group(1))")
    read CCE ROCM <<< "$v"
    . /etc/profile >/dev/null 2>&1
    module load cce/$CCE craype-accel-amd-gfx942 rocm/$ROCM
    module unload cray-mpich
    export FC=ftn CC=cc CXX=CC
    export CMAKE_PREFIX_PATH=$ROOT/results/apps/deps/hipfort-cce$CCE:${CMAKE_PREFIX_PATH:-}
    # CCE replaces some loops by LibSci calls (maxloc -> idamax); the
    # LibSci module ignores itself without cray-mpich, which the catalog's
    # recipe unloads: link LibSci's serial library by path
    export LDFLAGS="-L${CRAY_LIBSCI_PREFIX_DIR}/lib -lsci_cray ${LDFLAGS:-}"
    if [ "$STEP" = build ] && [ -f "$W/simulation_staging.txt" ]; then
      rm -f "$(cat "$W/simulation_staging.txt")/CMakeCache.txt"
    fi
    ;;
  nvhpc|nvhpc269)
    B=$(python3 -I -c "import sys; sys.path.insert(0,'$ROOT'); from offload.engine.toolchains import TOOLCHAINS as T; print(T['$TC'].fc.rsplit('/',1)[0])")
    export PATH=$B:$PATH FC=$B/nvfortran CC=$B/nvc CXX=$B/nvc++
    export LD_LIBRARY_PATH=$(dirname $B)/lib
    export MFC_CUDA_CC=80
    ;;
  *) echo "unknown toolchain $TC"; exit 2 ;;
esac
J=${JOBS:-32}
case $STEP in
  build)
    ./mfc.sh build -t pre_process simulation --gpu $GPU --no-mpi -j $J > "$W/build.log" 2>&1
    rc=$?
    echo "mfc build rc=$rc" | tee -a "$W/build.log"
    # a failed build: compile every object that can be compiled (-k), one
    # at a time, so each file's outcome is in its own block of the log
    for d in build/staging/*/; do
      if [ -f "$d/Makefile" ] && grep -q "MFC_SIMULATION:BOOL=ON" "$d/CMakeCache.txt" 2>/dev/null; then
        echo "$d" > "$W/simulation_staging.txt"
        if [ $rc -ne 0 ]; then
          (cd "$d" && make -k -j1 simulation > "$W/make_k.log" 2>&1)
        fi
      fi
    done
    ;;
  test|rerun)
    UUIDS=$(grep -v '^#' "$ROOT/data/bench/apps/mfc_tests.txt" | awk '{print $1}')
    case $MODE in
      unified) export HSA_XNACK=1 ;;
      copy) [ "${TC#nvhpc}" = "$TC" ] && export HSA_XNACK=0 ;;
    esac
    [ "$GPU" = mp ] && export OMP_TARGET_OFFLOAD=MANDATORY
    if [ "$STEP" = rerun ]; then
      RUN=()
      if [ "${TC#nvhpc}" != "$TC" ] && command -v nvidia-smi >/dev/null; then
        # a GPU no other user's process holds; the per-GPU run lock; nice
        busy=""
        while IFS=, read -r uuid pid; do
          owner=$(ps -o user= -p "${pid// /}" 2>/dev/null)
          [ "$owner" != "$(id -un)" ] && busy="$busy ${uuid// /}"
        done < <(nvidia-smi --query-compute-apps=gpu_uuid,pid --format=csv,noheader)
        G=${RERUN_GPU:-}
        if [ -z "$G" ]; then
          while IFS=, read -r idx uuid; do
            grep -q "${uuid// /}" <<< "$busy" || { G=${idx// /}; break; }
          done < <(nvidia-smi --query-gpu=index,uuid --format=csv,noheader)
        fi
        uuid=$(nvidia-smi --query-gpu=index,uuid --format=csv,noheader | awk -F', ' -v g="$G" '$1==g {print $2}')
        if [ -z "$G" ] || [ -z "$uuid" ] || grep -q "$uuid" <<< "$busy"; then
          echo "no free GPU (${G:-none}): refused"; exit 2
        fi
        export CUDA_VISIBLE_DEVICES=$G
        RUN=(flock "/tmp/compliant-run-$(id -u)-gpu$G.lock" nice -n 10)
      fi
      "${RUN[@]}" timeout --kill-after=30 "${RERUN_TIMEOUT:-3600}" \
        ./mfc.sh test --no-build --gpu $GPU --no-mpi -j 1 --no-examples --no-chemistry -o $RERUN > "$W/test.$MODE.rerun.log" 2>&1
      echo "mfc test rc=$?" | tee -a "$W/test.$MODE.rerun.log"
      echo "exit at $(date -Is)"
      exit 0
    fi
    rm -f tests/failed_uuids.txt
    ./mfc.sh test --no-build --gpu $GPU --no-mpi -j ${TJOBS:-4} --no-examples --no-chemistry -o $UUIDS > "$W/test.$MODE.log" 2>&1
    echo "mfc test rc=$?" | tee -a "$W/test.$MODE.log"
    cp -f tests/failed_uuids.txt "$W/failed.$MODE.txt" 2>/dev/null || : > "$W/failed.$MODE.txt"
    # each test's own output (pre_process + simulation)
    mkdir -p "$W/out.$MODE"
    for u in $UUIDS; do
      [ -f "tests/$u/out_pre_sim.txt" ] && cp -f "tests/$u/out_pre_sim.txt" "$W/out.$MODE/$u.txt"
    done
    ;;
esac
echo "exit at $(date -Is)"
