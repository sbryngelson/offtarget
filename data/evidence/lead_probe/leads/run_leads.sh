#!/bin/bash
# The three leads on one compute node (Tuolumne, or Tioga from
# its copy). Usage (from the repository root):
#   flux run -N1 -q pdebug --job-name=compile-test-run-leads -t 40m data/evidence/lead_probe/leads/run_leads.sh tuolumne
ulimit -c 0
M=${1:-tuolumne}
cd "${T47_ROOT:-$PWD}" || exit 1
export T48_TMP=/tmp/${USER}_t47_leads
rm -rf "$T48_TMP"; mkdir -p "$T48_TMP" results/t47
${PY:-python3} -I data/evidence/lead_probe/leads/jobs.py "$M" > "results/t47/leads_$M.jobs.jsonl"
timeout --kill-after=10 1800 ${PY:-python3} -I data/evidence/gate_probe/probe.py \
  "results/t47/leads_$M.jobs.jsonl" "results/t47/leads_$M.jsonl" --workers 8
if [ "$M" = tuolumne ]; then
  # lead 3 without -fopenmp: the host program as plain Fortran
  for v in 19.0.0:6.4.3 20.0.2:6.4.3 21.0.3:7.2.0 21.0.4:7.2.0; do
    c=${v%%:*}; r=${v##*:}; d=$T48_TMP/tm_$c; mkdir -p "$d"
    cp data/evidence/lead_probe/leads/tm_host.f90 "$d/"
    ( cd "$d" && . /etc/profile >/dev/null 2>&1
      module load cce/$c craype-accel-amd-gfx942 rocm/$r >/dev/null 2>&1
      module unload cray-mpich >/dev/null 2>&1
      for o in -O0 -O2; do
        echo "== cce $c no-openmp $o"
        timeout --kill-after=10 300 ftn -h noomp $o -o tm tm_host.f90 2>&1 | tail -3
        timeout --kill-after=10 60 ./tm
      done ) >> "results/t47/leads_${M}_noomp.txt" 2>&1
  done
fi
rm -rf "$T48_TMP"
echo done
