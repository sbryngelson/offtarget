#!/bin/bash
# The tests the wingtip lane left for Tuolumne, on Tioga where they run
# (docs/tooling/wingtip.md, "Tests left for Tuolumne, on Tioga"). From this tree on
# a Tuolumne login node (it only copies and starts ssh):
#   tools/lanes/run_tioga_suite.sh results/offline/suite/<lane>.<time>
# (1) splits that run's tuolumne.txt by class (tools/lanes/tioga_suite.py split);
# (2) copies this tree (no sealed or holdout set; a fresh git commit there,
# so the tests that ask git work) and the corpus/ inputs to a directory of
# its own on /p/vast1; (3) runs the Tioga classes in ONE foreground pdebug
# job (tools/lanes/tioga_suite_job.sh); (4) copies the junit files and logs back
# to <run>/tioga/ and writes there tioga.txt (passed on Tioga), failed.tsv
# and tuolumne.txt (what is left for Tuolumne); (5) deletes the copy.
# Exit: 1 when a test failed on Tioga or a step failed; 2 usage.
set -u
cd "$(dirname "$0")/../.." || exit 1
RUN=${1:-}
[ -f "$RUN/tuolumne.txt" ] || { echo "usage: $0 RUN_DIR (with tuolumne.txt)" >&2; exit 2; }
HOST=tio
DEST=$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import registry; print(registry().campaign_lanes["tioga"])')/wt-tsuite-$(basename "$RUN")
SSH="ssh -o BatchMode=yes -o ConnectTimeout=30"
OUT=$RUN/tioga
mkdir -p "$OUT/lists"
python3 -I tools/lanes/tioga_suite.py split "$RUN/tuolumne.txt" "$OUT/lists" || exit 1
T=$(mktemp -d "${TMPDIR:-/tmp}/tsuite.XXXXXX") || exit 1
trap 'rm -rf "$T"' EXIT
git ls-files -co --exclude-standard -z | grep -zvE '^(results|corpus|spec)(/|$)' |
  python3 -I tools/lanes/tioga_suite.py copy-files > "$T/code.list" || exit 1
python3 -I tools/lanes/tioga_suite.py inputs | sed 's|^corpus/||' > "$T/corpus.list" || exit 1
rev=$(git rev-parse --short HEAD)
# your own settings (install paths) travel with the copy as its catalog/local.yaml
python3 -I -c 'import sys, yaml; sys.path.insert(0, ".")
from offload.engine import localcfg
print(yaml.safe_dump({n: localcfg.overlay(n, {}) for n in ("machines.yaml", "toolchains.yaml")}))' > "$T/local.yaml" || exit 1

timeout 120 $SSH $HOST "test ! -e $DEST && mkdir -p $DEST/results $DEST/corpus $DEST/.tsuite" ||
  { echo "refused: $HOST:$DEST exists or cannot be made" >&2; exit 1; }
timeout 1800 rsync -a --from0 --files-from="$T/code.list" -e "$SSH" ./ "$HOST:$DEST/" &&
  timeout 600 rsync -a --files-from="$T/corpus.list" -e "$SSH" corpus/ "$HOST:$DEST/corpus/" &&
  timeout 120 rsync -a -e "$SSH" "$OUT/lists/" "$HOST:$DEST/.tsuite/lists/" &&
  timeout 120 rsync -a -e "$SSH" "$T/local.yaml" "$HOST:$DEST/catalog/local.yaml" &&
  timeout 600 $SSH $HOST "builtin cd $DEST && git init -q && git add -A &&
    git -c user.name=copy -c user.email=copy@localhost commit -q -m 'copy of $rev'" ||
  { echo "copying to $HOST:$DEST failed (left there)" >&2; exit 1; }

# one foreground job; the outer bound allows ~10 minutes of queue wait
timeout 4500 $SSH $HOST "builtin cd $DEST && flux run -q pdebug -N1 -n1 -t 60m --job-name=compile-test-tioga-suite bash tools/lanes/tioga_suite_job.sh"
echo "tioga job exit $?"
timeout 600 rsync -a -e "$SSH" "$HOST:$DEST/.tsuite/out/" "$OUT/" ||
  { echo "copying back failed: $HOST:$DEST left in place" >&2; exit 1; }
timeout 600 $SSH $HOST "rm -rf $DEST"
python3 -I tools/lanes/tioga_suite.py after "$RUN/tuolumne.txt" "$OUT" "$OUT"/*.xml
