#!/bin/bash
# GCC's compile-only catalog sweep (tools/campaigns/gcc_compile_sweep.py: Fortran and
# C OpenMP 5.0/5.2/6.0, Fortran OpenACC 3.4) and the offload link-failure
# probes (tests/data/gcc_probes) with one toolchain, no GPU. Bounded
# (LIMIT_S in all), WORKERS compiles (wingtip: at most 4, nice, in the cap).
#   wingtip: TC=gcc_sm80 tools/jobs/run_gcc_sweep.sh   (detached: setsid nohup)
#   Tioga:   TC=gcc_g90 WORKERS=32 inside one bounded interactive flux run
# Output: results/gcc/$TC/sweep.<f90|c|acc>.jsonl, probes.log
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
set -u
cd "$(dirname "$0")/../.."
ulimit -c 0
. tools/jobs/toolchains.sh  # generated from catalog/toolchains.yaml: the lanes' toolchains
TC=${TC:?TC=one of $TC_LANE_gcc}
tc_check "$TC" gcc || exit 2
PY=${PY:-python3}
WORKERS=${WORKERS:-4}
LIMIT_S=${LIMIT_S:-3000}
NICE=""
if [ "$(tc_machine "$TC")" = wingtip ]; then
  [ "$WORKERS" -le 4 ] || { echo "at most 4 compiles on wingtip"; exit 2; }
  NICE="nice -n 10"
fi
R=results/gcc/$TC; mkdir -p "$R"
END=$(( $(date +%s) + LIMIT_S ))
echo "host $(hostname) $(date -Is) TC=$TC workers $WORKERS"
for spec in "f90:50 52 60" "c:50 52 60" "acc:34"; do
  tag=${spec%%:*}; V=${spec#*:}; L=$tag; [ "$tag" = acc ] && L=f90
  left=$(( END - $(date +%s) )); [ "$left" -gt 60 ] || break
  $NICE timeout --kill-after=30 "$left" $PY -I tools/campaigns/gcc_compile_sweep.py \
    --toolchain "$TC" --lang "$L" --versions $V --workers "$WORKERS" \
    --limit-s $((left - 30)) --out "$R/sweep.$tag.jsonl"
  rc=$?
  echo "$tag exit $rc $(date -Is) rows $(wc -l < "$R/sweep.$tag.jsonl")"
done
# the probes, compiled with the toolchain's own command (its prelude too)
P=tests/data/gcc_probes
T=$(mktemp -d "${TMPDIR:-/tmp}/gccprobe.XXXXXX")
for L in c f90; do
  script=$($PY -I -c "
import dataclasses, sys
sys.path.insert(0, '.')
from offload.engine.harness import compile_script
from offload.engine.toolchains import TOOLCHAINS
t = TOOLCHAINS['$TC']
t = dataclasses.replace(t.for_mode(t.xnack_modes[0]), lang='$L')
print(compile_script(t, '$P/link_main.$L $P/link_ext.$L', '$T/link_$L.out',
                     '-O2', '$T'))")
  echo "=== probe link_$L"
  $NICE timeout --kill-after=10 300 bash -c "$script" > "$R/probe.link_$L.log" 2>&1
  echo "exit status: $?" >> "$R/probe.link_$L.log"
  cat "$R/probe.link_$L.log"
done
rm -rf "$T"
echo "done $(date -Is)"
