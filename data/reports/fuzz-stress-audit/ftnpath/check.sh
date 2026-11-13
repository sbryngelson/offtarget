#!/bin/bash
# Re-evaluate the committed sweep rows against the split rule (tools/campaigns/ftn_cif_split.py eval).
# Columns of the summary: count, predicted split (0|1), aborted (0|1), messages printed.
# Each record file (*.Ttmp) was captured (tools/jobs/run_ftn_cif_split.sh capture) in the directory named below;
# the sweeps compiled the program of that record file (tu12: data/reports/fuzz-stress-audit/ftn-path-abort-tu12.f90;
# chainN: genchain.py N) as stress.f90, -fopenmp -O2 -c, in each listed directory.
cd "$(dirname "$0")" || exit 1
T=../../../../tools/campaigns/ftn_cif_split.py
CR=/tmp/<user>-stress/st-tu.plain-omp-12-1-abcd1234
B200=/tmp/cce-cif/$(printf 'b%.0s' $(seq 1 200))
s() { python3 -I $T eval "$@" | awk '{m="-"; for (i = 4; i <= NF; i++) if ($i ~ /^msgs=/) m = $i; print $1, $2, m}' | sort | uniq -c; }
n=0
for x in "tu12 CCE 19 (single-character variants)|tu12.Ttmp $CR sweep1.log sweep2.log" \
         "tu12 CCE 19 (designed)|tu12.Ttmp $CR sweep3-19.0.0.log" \
         "tu12 CCE 20.0.2 (designed)|tu12.Ttmp $CR sweep3-20.0.2.log" \
         "tu12 CCE 21.0.3 (designed)|tu12.Ttmp $CR sweep3-21.0.3.log" \
         "chain12 CCE 19|chain12.Ttmp /tmp/cce-cif/base sweep4.log" \
         "chain3 CCE 19|chain3.Ttmp $B200 sweep5-3.log" \
         "chain6 CCE 19|chain6.Ttmp $B200 sweep5-6.log"; do
  echo "== ${x%%|*}"; s ${x#*|}
  n=$((n + $(python3 -I $T eval ${x#*|} | wc -l)))
done
echo "compiles: $n"
echo "aborts without a predicted split: $(for x in "tu12.Ttmp $CR sweep1.log sweep2.log sweep3-19.0.0.log sweep3-20.0.2.log sweep3-21.0.3.log" "chain12.Ttmp /tmp/cce-cif/base sweep4.log" "chain3.Ttmp $B200 sweep5-3.log" "chain6.Ttmp $B200 sweep5-6.log"; do python3 -I $T eval $x; done | awk '$1 == 0 && $2 == 1' | wc -l)"
