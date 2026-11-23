#!/bin/bash
# The leads' reductions (tools/campaigns/leads.py reduce): the unfinished entries of
# results/leads/queue.jsonl in order, within MINUTES (default 25); each resumes from its checkpoint,
# so the next job continues where this one stopped. Then the catalog is asked about each result.
#   flux run -q pdebug -N1 -t 30 --job-name=compile-leads --env=SPINDLE_FLUXOPT=disable \
#     env -i HOME=$HOME USER=$USER bash -lc "cd $PWD && tools/jobs/run_leads_reduce.sh"
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}" || exit 1
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
python3 -I tools/campaigns/leads.py reduce --minutes "${MINUTES:-25}" || exit 1
python3 -I tools/campaigns/leads.py recheck
echo "done $(date -Is)"
