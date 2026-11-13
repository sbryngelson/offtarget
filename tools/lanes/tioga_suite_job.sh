#!/bin/bash
# The Tioga half of tools/lanes/run_tioga_suite.sh: runs inside its ONE
# foreground pdebug job, in the copy on /p/vast1, the classes of
# tools/lanes/tioga_suite.py that lists in .tsuite/lists/ name (side by side,
# each pytest bounded by `timeout`): tioga and tioga-inputs as is,
# tioga-afar with AFAR's run-time libraries on LD_LIBRARY_PATH (as the
# afar_g90 toolchain runs), tioga-nogpu with the GPU hidden
# (ROCR_VISIBLE_DEVICES set empty: the harness's node check then has no
# GPU to compare). Junit files and logs go to .tsuite/out/.
ulimit -c 0
cd "$(dirname "$0")/../.." || exit 1
# Tuolumne's Python and gfortran (/usr/tce/bin), node for the page checks
export PATH=/usr/tce/bin:$HOME/.nvm/versions/node/v22.22.2/bin:/usr/bin:/bin
[ -f catalog/local.yaml ] && export OFFLOAD_TEST_LOCAL=$PWD/catalog/local.yaml     # the user's install paths (tests/conftest.py)
AV=${AV:-$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import TOOLCHAINS as T; print(T["afar_g90"].install_root)')}
L=.tsuite/lists
O=.tsuite/out
mkdir -p $O
T=/tmp/$USER-tsuite-${FLUX_JOB_ID:-$$}
mkdir -p "$T"
export TMPDIR=$T
PYT="python3 -I -m pytest -p no:cacheprovider -q -rfEs"
PROBE='import sys; sys.path.insert(0, "."); from offload.engine.toolchains import detect_gpu; print(detect_gpu()[0] or "none")'
{
  echo "host $(hostname) job ${FLUX_JOB_ID:-none} $(date -Is) rev $(git log -1 --format=%s)"
  command -v python3 gfortran node google-chrome
  echo "GPU: $(python3 -I -c "$PROBE"); hidden: $(ROCR_VISIBLE_DEVICES= python3 -I -c "$PROBE")"
} > $O/env.txt 2>&1

run() {  # CLASS CMD...: the class's list, if any
  local c=$1; shift
  [ -s $L/$c.txt ] || return 0
  local t0=$(date +%s)
  timeout --kill-after=30 2700 "$@" $PYT --junitxml=$O/$c.xml \
    $(cat $L/$c.txt) > $O/$c.log 2>&1
  echo "$c exit $? after $(( $(date +%s) - t0 )) s" >> $O/status.txt
}
: > $O/status.txt
run tioga env &
run tioga-inputs env &
run tioga-afar env LD_LIBRARY_PATH=$AV/lib:$AV/lib/llvm/lib &
if [ "$(ROCR_VISIBLE_DEVICES= python3 -I -c "$PROBE")" = none ]; then
  run tioga-nogpu env ROCR_VISIBLE_DEVICES= &
else
  echo "tioga-nogpu not run: the GPU stays visible" >> $O/status.txt
fi
wait
# the page checks leave headless Chrome processes (their profile is under
# $T) that hold the job's output open: without this the job never ends
pkill -u "$USER" -f -- "$T"
sleep 3
rm -rf "$T"
cat $O/status.txt
