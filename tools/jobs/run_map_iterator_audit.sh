#!/bin/bash
# Follow-up in ONE flux allocation (THP=always): (1) the oracle
# audits of the fixed map.iterator programs (Fortran and C), merged into
# the committed audits; (2) every program whose two memory modes differ in
# the full copy-mode run (results/task26/confirm.<lang>.txt) and the fixed
# programs, run again in BOTH modes on this one node, in place in the work
# copies (run_matrix.py rerun keeps every other row); (3) the map audit of
# the fixed programs (their old rows removed first). Submit:
#   flux batch -q pbatch -N1 -t 60 --setattr=thp=always \
#     --output=results/task26/confirm.log tools/jobs/run_map_iterator_audit.sh
ulimit -c 0
cd "${COMPLIANT_ROOT:-$PWD}"
echo "host $(hostname) job ${FLUX_JOB_ID:-none} start $(date -Is)"
echo "thp: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
T=/tmp/${USER:-user}-t26c-${FLUX_JOB_ID:-$$}
mkdir -p $T
export TMPDIR=$T
ONLY='^omp\.clause\.map\.iterator$'
python3 -I tools/campaigns/oracle_audit.py --versions 52 60 --only "$ONLY" --merge \
  --workers 8
echo "audit f90 exit $? at $(date -Is)"
python3 -I tools/campaigns/oracle_audit.py --lang c --versions 52 60 --only "$ONLY" \
  --merge --workers 8
echo "audit c exit $? at $(date -Is)"
WHY="Same-node confirmation of the memory-mode differences (both modes in one allocation) and the map.iterator programs fixed to one iterator value"
for X in 1 0; do
  python3 -I tools/campaigns/run_matrix.py rerun --xnack $X --versions 50 52 60 \
    --toolchains afar cce19 cce20 cce21 --workers 16 \
    --programs $(cat results/task26/confirm.f90.txt) \
    --out results/task26/matrix.f90.work.jsonl --why "$WHY"
  echo "f90 xnack$X exit $? at $(date -Is)"
  python3 -I tools/campaigns/run_matrix.py rerun --lang c --xnack $X --versions 52 60 \
    --toolchains afar cce19 cce20 cce21 --workers 16 \
    --programs $(cat results/task26/confirm.c.txt) \
    --out results/task26/matrix.c.work.jsonl --why "$WHY"
  echo "c xnack$X exit $? at $(date -Is)"
done
python3 -I - <<'PY'
import json, glob
for f in glob.glob("results/map_audit/*.jsonl"):
    lines = open(f).read().splitlines()
    keep = [l for l in lines if "clause-map-iterator" not in
            json.loads(l)["program_id"]]
    if len(keep) != len(lines):
        open(f, "w").write("".join(l + "\n" for l in keep))
        print(f, "dropped", len(lines) - len(keep))
PY
for L in f90 c; do for V in 52 60; do for TC in afar cce19; do
  python3 -I tools/campaigns/map_audit.py run --lang $L --versions $V --toolchains $TC \
    --workers 8 --out results/map_audit/$L.$V.$TC.jsonl
done; done; done
echo "map audit exit $? at $(date -Is)"
echo "leftover in own TMPDIR:"; ls -A $T
rm -rf $T
echo done
