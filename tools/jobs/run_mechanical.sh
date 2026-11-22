#!/bin/bash
# The legality records of every finding (docs/tooling/regenerate.md, "legality"): AMD's front end
# on the findings no run of another family witnesses (catalog/finding_witness.yaml), then every
# record from its program, the committed rows and the stored front-end rows.
# Submit (pdebug, a few minutes):
#   flux run -q pdebug -N1 -t 30 --job-name=compile-legality --env=SPINDLE_FLUXOPT=disable \
#     env -i HOME=$HOME USER=$USER bash -lc "cd $PWD && tools/jobs/run_mechanical.sh"
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}" || exit 1
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
python3 -I tools/review/review.py mechanical --frontend || exit 1
echo "done $(date -Is)"
