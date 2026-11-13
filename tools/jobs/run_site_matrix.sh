#!/bin/bash
# The public site's finding-matrix runs (tools/derive/finding_matrix.py plan): the derived cases
# (data/vendor/checks/cases-site.json) and the vendor cases still missing, in one gate
# environment ENV (a, b, c, d; c is submitted as its own job so it lands on another node).
#   Tuolumne (pbatch only):
#     flux batch -q pbatch -N1 -t 120 --setattr=thp=always \
#       --output=data/vendor/checks/logs/site.tuo.ENV.%j.log tools/jobs/run_site_matrix.sh tuolumne ENV
#   wingtip (inside compliant.slice; one free GPU; at most 2 compiles):
#     setsid nohup bash tools/jobs/run_site_matrix.sh wingtip ENV GPU > LOG 2>&1 < /dev/null &
#   GCC (a family the vendor cases were not written for: every case, vendor and derived,
#   repro only, separate memory): wingtip with GCC=1; Tioga (no batch queue: one
#   supervised interactive pdebug job of at most an hour per environment, (c) on
#   another node than (a)) from the /p/vast1 copy:
#     GCC=1 setsid nohup bash tools/jobs/run_site_matrix.sh wingtip ENV GPU > LOG ... &
#     flux run -q pdebug -N1 -n1 -t 60m --job-name=compile-test-gcc-site-ENV \
#       tools/jobs/run_site_matrix.sh tioga ENV
#   GCC on the other AMD GPUs (the install's device libraries cover gfx942 and gfx950; GCC_ROOT and
#   GCC_ROCM name the install and the ROCm it loads): Tuolumne's MI300A in both memory modes, the
#   MI300X and MI350X (Slurm on the AMD cluster; PY names its Python) in copy memory:
#     GCC=1 GCC_ROOT=... GCC_ROCM=... flux batch -q pbatch -N1 -t 120 tools/jobs/run_site_matrix.sh tuolumne ENV
#     GCC=1 GCC_ROOT=... GCC_ROCM=... PY=... GPUS=0 sbatch -p mi3001x ... tools/jobs/run_site_matrix.sh mi300x ENV
# Writes data/vendor/checks/results/site-<machine>.<env>.jsonl; `tools/derive/finding_matrix.py pack`
# turns them into the committed results-site/.
M=$1; E=$2; G=${3:-0}
# the tree: COMPLIANT_ROOT, else the directory the job was submitted from (flux batch runs a copy
# of this script from elsewhere)
cd "${COMPLIANT_ROOT:-$PWD}" || exit 1
case "$M" in
  wingtip) . tools/jobs/wingtip_cap.sh || exit 1 ;;
  tuolumne|tioga) ;;
  mi300x|mi350x) [ -n "${GCC:-}" ] || { echo "$M: GCC only" >&2; exit 2; } ;;
  *) echo "machine: tuolumne, wingtip, tioga (GCC only), mi300x or mi350x (GCC only)" >&2; exit 2 ;;
esac
. tools/jobs/toolchains.sh  # generated from catalog/toolchains.yaml: tc_list LANE [MACHINE]
cd data/vendor/checks || exit 1
ulimit -c 0
OUT=results/site-$M.$E.jsonl
# one build directory per run: two runs (another environment, the GCC rows) on one host must not
# share it, since each run removes its directory at the end (the other's builds would vanish)
TMP="/tmp/${USER}_site.$$"
# GCC rows go to files of their own (results-site/site-<machine>-gcc.<env>.jsonl.gz once packed)
{ [ "$M" = tioga ] || [ -n "${GCC:-}" ]; } && OUT=results/site-$M-gcc.$E.jsonl
VENDOR_CASES=${VENDOR_CASES:-cce-ftn-cif-record-split-abort,nvhpc-managed-acc-shutdown-host-access}
# CASES=id,id narrows any branch to those derived cases of cases-site.json (the vendor cases are then not run).
# GCC only: VARIANTS=control (default repro) with CASES=id,id runs those derived cases' controls
# (cases-site.json) and nothing else; --resume skips what the output file already holds
GCC_VARIANTS=${VARIANTS:-repro}
GCC_FILES="cases.json cases-site.json"
# the site keys GCC's AMD cells by its MI300A toolchain (gcc); the machine gives the GPU
GCC_AMD=$(tc_list gcc tuolumne)
GCC_SEL=()
if [ -n "${CASES:-}" ]; then GCC_FILES=cases-site.json; GCC_SEL=(--cases "$CASES"); fi
echo "host $(hostname) machine $M env $E start $(date -Is)"
if [ "$M" = tioga ]; then
  gcc=(--machine tioga --env "$E" --toolchains "$GCC_AMD" --modes 0 --variants "$GCC_VARIANTS" --all-arches "${GCC_SEL[@]}"
       --workers 16 --compiles 16 --per-gpu 2 --gpus 0,1,2,3,4,5,6,7 --limit-s "${LIMIT_S:-3000}"
       --resume --tmp "$TMP" --out "$OUT")
  PY=/usr/tce/bin/python3   # Tioga's /usr/bin/python3 is 3.6
  for cf in $GCC_FILES; do
    timeout --kill-after=30 "${LIMIT_S:-3000}" $PY -I run_checks.py run --cases-file $cf "${gcc[@]}"
  done
elif [ -n "${GCC:-}" ] && [ "$M" != wingtip ]; then
  unset ROCR_VISIBLE_DEVICES
  modes=0; [ "$M" = tuolumne ] && modes=1,0
  gpus=${GPUS:-0,1,2,3}
  for cf in $GCC_FILES; do
    timeout --kill-after=30 "${LIMIT_S:-6600}" "${PY:-python3}" -I run_checks.py run --cases-file $cf \
      --machine "$M" --env "$E" --toolchains "$GCC_AMD" --modes "$modes" --variants "$GCC_VARIANTS" \
      --all-arches "${GCC_SEL[@]}" --workers 24 --compiles 24 --per-gpu 4 --gpus "$gpus" \
      --limit-s "${LIMIT_S:-6600}" --resume --tmp "$TMP" --out "$OUT"
  done
elif [ -n "${GCC:-}" ]; then
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "$G" | tr -d ' ')
  [ "${used:-1}" -lt 100 ] || { echo "GPU $G is in use ($used MiB): not starting"; exit 1; }
  for cf in $GCC_FILES; do
    timeout --kill-after=30 14400 nice -n 10 python3 -I run_checks.py run --cases-file $cf \
      --machine wingtip --env "$E" --toolchains "$(tc_list gcc wingtip)" --modes 0 --variants "$GCC_VARIANTS" --all-arches "${GCC_SEL[@]}" \
      --workers 2 --compiles 2 --gpus "$G" --resume --tmp "$TMP" --out "$OUT"
  done
elif [ "$M" = tuolumne ]; then
  unset ROCR_VISIBLE_DEVICES
  common=(--machine tuolumne --env "$E" --toolchains "$(tc_list tuolumne)" --modes 1,0
          --workers 24 --compiles 24 --limit-s "${LIMIT_S:-6600}" --resume --tmp "$TMP" --out "$OUT")
  if [ -n "${CASES:-}" ]; then   # CASES=id,id: only these derived cases (their repro and control), no vendor cases
    timeout --kill-after=30 6900 python3 -I run_checks.py run --cases "$CASES" --cases-file cases-site.json "${common[@]}"
  else
    timeout --kill-after=30 6900 python3 -I run_checks.py run --cases-file cases-site.json "${common[@]}"
    timeout --kill-after=30 1800 python3 -I run_checks.py run --cases "$VENDOR_CASES" "${common[@]}"
  fi
else
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "$G" | tr -d ' ')
  [ "${used:-1}" -lt 100 ] || { echo "GPU $G is in use ($used MiB): not starting"; exit 1; }
  timeout --kill-after=30 14400 nice -n 10 python3 -I run_checks.py run --cases-file cases-site.json ${CASES:+--cases "$CASES"} \
    --machine wingtip --env "$E" --toolchains "$(tc_list wingtip)" --modes 0,2 --workers 2 --compiles 2 \
    --gpus "$G" --resume --tmp "$TMP" --out "$OUT"
fi
rm -rf "$TMP"
echo "done $(date -Is)"
