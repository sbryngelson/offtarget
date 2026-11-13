#!/bin/bash
# the device-heap-temporary detector (compile only) over the Fortran program sets we hold (resumable)
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
export TMPDIR=/tmp/${USER}_devtemps_$$
mkdir -p "$TMPDIR"
for s in kbody-heap findings kbody-nbhd oop; do
  echo "== $s"; timeout -k 10 480 python3 -I tools/campaigns/devtemps.py scan $s --workers 32
done
for s in nested catalog stress fuzz kbody-pilot; do
  echo "== $s"; timeout -k 10 360 python3 -I tools/campaigns/devtemps.py scan $s --workers 32 --limit 100
done
python3 -I tools/campaigns/devtemps.py table > results/devtemps/table.md
rm -rf "$TMPDIR"
echo finished
