#!/bin/bash
# (docs/tooling/regenerate.md, step widen-batch): the confirmer on the
# widened catalog's failing cells (stored evidence only, no runs) ->
# results/confirm/batch_widen.jsonl, then its inputs stamp. Submit:
#   flux batch -q pbatch -N1 -t 30 --output=results/widen/confirm.log \
#     tools/jobs/run_widen_confirm.sh
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}" || exit 1
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "git $(git rev-parse --short HEAD)"
ALL="rejected ice timeout harness_error accepted_ignored crash run_error wrong_answer fell_back_to_host"
TAG=${TAG:-widen}
C=results/confirm
[ -f $C/batch_widen.jsonl ] && cp -p $C/batch_widen.jsonl $C/batch_widen.pre-$TAG.jsonl
python3 -I tools/confirm.py batch --from results/widen/matrix.jsonl \
  --outcomes $ALL --out results/confirm/batch_widen.jsonl \
  && python3 -I tools/regenerate.py --stamp-widen-batch \
  && { [ ! -f $C/batch_widen.pre-$TAG.jsonl ] || \
       python3 -I tools/derive/confirm_batch_changes.py --rebuild $TAG \
         --pair $C/batch_widen.pre-$TAG.jsonl $C/batch_widen.jsonl; }
echo "exit $? at $(date -Is)"
