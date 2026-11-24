#!/bin/bash
# The reproduction gate of the findings tools/campaigns/leads.py wrote and has not finished, in gate
# environment ENV (a, b or d on one node, c on another; tools/jobs/run_finding_gate.sh), with its
# AFAR_ROOT, AFAR244_ROOT, GCC_ROOT and GCC_ROCM.
#   flux run -q pdebug -N1 -t 30 --job-name=compile-gate-ENV --env=SPINDLE_FLUXOPT=disable [--requires=...] \
#     env -i HOME=$HOME USER=$USER GCC_ROOT=... GCC_ROCM=... bash -lc "cd /path/to/checkout && tools/jobs/run_leads_gate.sh ENV"
cd "${COMPLIANT_ROOT:-$PWD}" || exit 1
CASES=$(python3 -I tools/campaigns/leads.py cases) || exit 1
[ -n "$CASES" ] || { echo "no written finding to gate"; exit 0; }
CASES=$CASES exec bash tools/jobs/run_finding_gate.sh "${1:?usage: run_leads_gate.sh ENV}"
