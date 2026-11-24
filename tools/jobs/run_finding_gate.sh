#!/bin/bash
# The reproduction gate of new findings on Tuolumne: their site check cases (CASES, comma-separated
# ids of data/vendor/checks/cases-site.json, from tools/derive/finding_matrix.py cases) in gate
# environment ENV (a, b, c or d; c on another node than a): the compilers under test
# (tools/jobs/run_site_matrix.sh), then GCC in copy memory, repro and control. AFAR_ROOT and
# AFAR244_ROOT name the AFAR installs, GCC_ROOT and GCC_ROCM the GCC install and its ROCm.
#   flux run -q pdebug -N1 -t 30 --job-name=compile-gate-ENV --env=SPINDLE_FLUXOPT=disable \
#     [--requires=-host:HOST_OF_A for c] env -i HOME=$HOME USER=$USER CASES=... AFAR_ROOT=... AFAR244_ROOT=... \
#     GCC_ROOT=... GCC_ROCM=... \
#     bash -lc "cd /path/to/checkout && tools/jobs/run_finding_gate.sh ENV"
E=${1:?usage: run_finding_gate.sh ENV}
cd "${COMPLIANT_ROOT:-$PWD}" || exit 1
: "${CASES:?CASES names the check cases}" "${AFAR_ROOT:?}" "${AFAR244_ROOT:?}" "${GCC_ROOT:?}" "${GCC_ROCM:?}"
export AFAR_ROOT AFAR244_ROOT
echo "host $(hostname) env $E start $(date -Is)"
CASES=$CASES LIMIT_S=${LIMIT_S:-400} bash tools/jobs/run_site_matrix.sh tuolumne "$E"
GCC=1 GCC_MODES=0 CASES=$CASES LIMIT_S=200 bash tools/jobs/run_site_matrix.sh tuolumne "$E"
GCC=1 GCC_MODES=0 VARIANTS=control CASES=$CASES LIMIT_S=200 bash tools/jobs/run_site_matrix.sh tuolumne "$E"
echo "done $(date -Is)"
