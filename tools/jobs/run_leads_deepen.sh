#!/bin/bash
# The leads' confirmed drafts whose reduction stopped at its budget, reduced further
# (tools/campaigns/leads.py deepen: from their checkpoints, WORKERS candidates at once, within
# MINUTES, default 20), then recheck and the confirmer on the smaller programs (ADVANCE, default 7).
# The job's FLUX_JOB_ID goes through env -i (expanded in the job: the confirmer's local runs need it):
#   flux run -q pdebug -N1 -t 30 --job-name=compile-leads --env=SPINDLE_FLUXOPT=disable \
#     bash -c 'exec env -i HOME="$HOME" USER="$USER" FLUX_JOB_ID="$FLUX_JOB_ID" bash -lc \
#     "cd /path/to/checkout && tools/jobs/run_leads_deepen.sh"'
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}" || exit 1
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
python3 -I tools/campaigns/leads.py deepen --minutes "${MINUTES:-20}" --workers "${WORKERS:-4}" || exit 1
python3 -I tools/campaigns/leads.py recheck
python3 -I tools/campaigns/leads.py advance --minutes "${ADVANCE:-7}"
echo "done $(date -Is)"
