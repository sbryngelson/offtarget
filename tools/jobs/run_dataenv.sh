#!/bin/bash
# The data-environment pilot on a flux machine (Tuolumne, or Tioga
# from its copy of the tree), TWO nodes. Phases, each on both nodes:
#   1. runs: `tools/dataenv/dataenv.py run`, half of the cells per node;
#   2. the reproduction gate over the failing rows: (a), (b), (d) on the
#      row's own node, then (c) on the other node;
#   3. (node 0, Tuolumne only) the oracle and map audits on AFAR and CCE 19.
# Usage (only after the maintainer's go):
#   flux batch -q pbatch -N2 -t 60 --setattr=thp=always \
#     --output=results/dataenv/logs/run.%j.log \
#     tools/jobs/run_dataenv.sh tuolumne 2400 24 pilot
# Arguments: MACHINE LIMIT_S WORKERS NAME. Resumable: done cells, reruns
# and audit runs are skipped, so a chunk that hits LIMIT_S is resubmitted.
ulimit -c 0
cd "${DE_ROOT:-$PWD}" || exit 1
[ -f tools/dataenv/dataenv.py ] || { echo "not a repository root: $PWD"; exit 1; }
JOB=$(flux getattr jobid 2>/dev/null || echo "p$$")
M=$1; LIM=$2; W=$3; NAME=$4
PY=${PY:-python3}
unset ROCR_VISIBLE_DEVICES
mkdir -p results/dataenv/logs
echo "job $JOB on $(hostname) start $(date -Is) git $(git rev-parse --short HEAD 2>/dev/null)"
END=$(( $(date +%s) + LIM ))
phase() {   # phase P on half K
  local P=$1 K=$2 REM
  export TMPDIR=/tmp/${USER}_de_${JOB}_${K} GATE_TMP=/tmp/${USER}_degate_${JOB}_${K}
  mkdir -p "$TMPDIR" "$GATE_TMP"
  REM=$((END - $(date +%s)))
  [ "$REM" -gt 60 ] || return 0
  case $P in
    run) timeout --kill-after=10 $((REM + 900)) $PY -I tools/dataenv/dataenv.py run \
           --name "$NAME" --machine "$M" --workers "$W" --shard "$K/2" --limit-s "$REM" ;;
    abd) timeout --kill-after=10 $((REM + 900)) $PY -I tools/dataenv/dataenv.py gate \
           --name "$NAME" --machine "$M" --envs a,b,d --node same --workers "$W" ;;
    c)   timeout --kill-after=10 $((REM + 900)) $PY -I tools/dataenv/dataenv.py gate \
           --name "$NAME" --machine "$M" --envs c --node other --workers "$W" ;;
    audit) [ "$M" = tuolumne ] && [ "$K" = 0 ] && timeout --kill-after=10 $((REM + 900)) \
           $PY -I tools/dataenv/dataenv.py audit --name "$NAME" --workers "$W" --limit-s "$REM" ;;
  esac
  rm -rf "$TMPDIR" "$GATE_TMP"
}
export -f phase
export M W PY END JOB NAME
for P in run abd c audit; do
  flux run -N1 -n1 --exclusive bash -c "phase $P 0" >> results/dataenv/logs/$P.0.$JOB.log 2>&1 &
  flux run -N1 -n1 --exclusive bash -c "phase $P 1" >> results/dataenv/logs/$P.1.$JOB.log 2>&1 &
  wait
done
echo "all done $(date -Is)"
