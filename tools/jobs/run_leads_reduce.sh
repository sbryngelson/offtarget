#!/bin/bash
# The leads (tools/campaigns/leads.py): the unfinished reductions of results/leads/queue.jsonl in
# order within MINUTES (default 18; each resumes from its checkpoint, so the next job continues the
# queue, and a lead a finished reduction covers is skipped), the catalog asked again about each
# result (recheck), then the confirmer on each one still new within ADVANCE minutes (default 8).
#   flux run -q pdebug -N1 -t 30 --job-name=compile-leads --env=SPINDLE_FLUXOPT=disable \
#     env -i HOME=$HOME USER=$USER bash -lc "cd $PWD && tools/jobs/run_leads_reduce.sh"
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}" || exit 1
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
python3 -I tools/campaigns/leads.py reduce --minutes "${MINUTES:-18}" || exit 1
python3 -I tools/campaigns/leads.py recheck
python3 -I tools/campaigns/leads.py advance --minutes "${ADVANCE:-8}"
echo "done $(date -Is)"
