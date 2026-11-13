#!/bin/bash
# Rerun named cases on wingtip into separate files (results/wingtipfix.ENV.jsonl).
#   setsid nohup ~/t44/checks/wt_fix.sh GPU CASES VARIANTS "a b c d" > log 2>&1 &
. "$(dirname "$0")/wingtip_cap.sh" || exit 1
cd "$(dirname "$0")" || exit 1
ulimit -c 0
G=$1; C=$2; V=$3
for E in $4; do
  timeout --kill-after=30 7200 nice -n 10 python3 -I run_checks.py run --machine wingtip --env "$E" \
    --toolchains nvhpc,nvhpc269 --modes 0,2 --workers 2 --compiles 2 --gpus "$G" \
    --variants "$V" --cases "$C" --out results/wingtipfix.$E.jsonl
done
rm -rf /tmp/${USER}-t44
echo "fix done $(date -Is)"
