#!/bin/bash
# The reproduction gate's reruns on a flux machine (Tuolumne, or
# Tioga from its copy of the tree), on TWO nodes: each node runs one half
# of the planned rows in environments (a), (b) and (d), then the other
# half's environment (c), so (c) always runs on the other node.
#   flux batch -q pbatch -N2 -t 60 --setattr=thp=always \
#     --output=results/gate/logs/run.%j.log \
#     tools/jobs/run_gate.sh tuolumne 2400 8 catalog widen fuzz evidence
#   (repeat the submission until nothing is left: each chunk resumes)
#   (stress: fewer workers, a longer limit; pbatch)
# Arguments: MACHINE LIMIT_S WORKERS CAMPAIGN...; LIMIT_S: no new row is
# started after it (a started row finishes; leave its time in the
# walltime). Resumable: done environments are skipped.
ulimit -c 0
# flux batch runs a copy of this script from the submit directory: run
# from there (the repository root, or Tioga's copy of it)
cd "${GATE_ROOT:-$PWD}" || exit 1
[ -f tools/campaigns/gate.py ] || { echo "not a repository root: $PWD"; exit 1; }
JOB=$(flux getattr jobid 2>/dev/null || echo "p$$")
M=$1; LIM=$2; W=$3; shift 3
PY=${PY:-python3}
unset ROCR_VISIBLE_DEVICES
mkdir -p results/gate/logs
echo "job $JOB on $(hostname) start $(date -Is)"
echo "git $(git rev-parse --short HEAD 2>/dev/null || cat .wingtip_rev 2>/dev/null)"
half() {   # half K: per campaign, shard K in a,b,d then shard 1-K in c
  local K=$1 O=$((1 - $1)) C E REM
  # one root on every node and in every job: (c) on the other
  # node builds in the very path of (a)
  export GATE_TMP=/tmp/${USER}_gate
  mkdir -p "$GATE_TMP"
  for C in $CAMPS; do
    for E in "a,b,d $K" "c $O"; do
      REM=$((END - $(date +%s)))
      [ "$REM" -gt 60 ] || break 2
      set -- $E
      # BUDGETS="catalog=4 widen=1.2": this machine's share of a
      # campaign's GPU-hour budget (the ledger is per tree copy)
      B=$(echo "$BUDGETS" | tr ' ' '\n' | grep "^$C=" | cut -d= -f2)
      timeout --kill-after=10 $((REM + 1800)) $PY -I tools/campaigns/gate.py run \
        --campaign "$C" --machine "$M" --envs "$1" --shard "$2/2" \
        --workers "$W" --limit-s "$REM" --concurrent 2 \
        ${B:+--budget-gpu-h $B}
    done
  done
  echo "leftover in $GATE_TMP:"; ls -A "$GATE_TMP" | head
  rm -rf "$GATE_TMP"/GATE* "$GATE_TMP"/harness_* "$GATE_TMP"/fuzz_* \
    "$GATE_TMP"/st_* "$GATE_TMP"/confirm_* 2>/dev/null
  # the roots of earlier jobs (c) made again: removed when empty
  rmdir /tmp/${USER}_gate_* 2>/dev/null
}
export -f half
END=$(( $(date +%s) + LIM ))
export M LIM W PY END JOB BUDGETS CAMPS="$*"
flux run -N1 -n1 --exclusive bash -c 'half 0' > results/gate/logs/half0.$JOB.log 2>&1 &
flux run -N1 -n1 --exclusive bash -c 'half 1' > results/gate/logs/half1.$JOB.log 2>&1 &
wait
echo "all done $(date -Is)"
