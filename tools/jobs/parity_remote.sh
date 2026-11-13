#!/bin/bash
# Coverage parity (tools/campaigns/parity.py): a private copy of this tree on wingtip
# or Tioga for the GCC (and NVHPC) runs, and the results back.
#   tools/jobs/parity_remote.sh push wingtip|tioga
#   tools/jobs/parity_remote.sh pull wingtip|tioga      # -> results/parity/<machine>/
# The copy: tracked and new files as on disk, less the sealed unscored sets
# (tools/lanes/wingtip_offline.py code-files); of each harvest set only the dev
# programs (their list, sources and pre-run verdicts: a holdout program
# never leaves Tuolumne); the fuzz sample's stored legality verdicts; the
# stress pre-run verdicts (results/parity/stress, once checked); the five
# application clones the corpus builds (corpus/apps, no .git, no MFC).
# Results stay in the copy's results/ under the tools' usual paths and come
# back under results/parity/<machine>/ (never into the shared campaign
# directories).
# Roots: <campaign_lanes of the machine>/parity-lane (wingtip) and /wt-parity (Tioga).
set -eu
cd "$(dirname "$0")/../.."
case "${2:-}" in
  tioga) HOST=${HOST:-tio}; ROOT=$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import registry; print(registry().campaign_lanes["tioga"])')/wt-parity
         SSH="ssh -o BatchMode=yes" ;;
  wingtip) HOST=${HOST:-wingtip}; ROOT=$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import registry; print(registry().campaign_lanes["wingtip"])')/parity-lane
           SSH="ssh -o BatchMode=yes -o ControlMaster=auto -o ControlPath=$HOME/.ssh/cm-compliant-%r@%h:%p -o ControlPersist=10m" ;;
  *) echo "usage: $0 push|pull wingtip|tioga"; exit 2 ;;
esac
OUTS="results/harvest/parity results/harvest-known/parity results/harvest2/parity
results/stress results/fuzz results/apps/runs results/apps/build-logs results/parity"
case "$1" in
  push)
    $SSH "$HOST" "mkdir -p $ROOT/results"
    T=$(mktemp -d "${TMPDIR:-/tmp}/parpush.XXXXXX") || exit 1
    git ls-files -co --exclude-standard -z | grep -zv -E "^(results|corpus|spec)$" |
      grep -zv -E "^data/bench/[^/]*holdout" |   # no holdout set, scored or not (brief)
      python3 -I tools/lanes/wingtip_offline.py code-files > "$T/code.list" || exit 1
    rsync -a --from0 --files-from="$T/code.list" -e "$SSH" ./ "$HOST:$ROOT/"
    git rev-parse --short HEAD > "$T/rev"
    rsync -a -e "$SSH" "$T/rev" "$HOST:$ROOT/.wingtip_rev"
    for S in harvest harvest-known harvest2; do
      R=results/$S
      mkdir -p "$T/$S"
      python3 -I -c '
import json, sys
progs = [json.loads(l) for l in open(sys.argv[2] + "/programs.jsonl") if l.strip()]
dev = [p for p in progs if not p["holdout"]]
ids = {p["id"] for p in dev}
open(sys.argv[1] + "/programs.jsonl", "w").write("".join(json.dumps(p) + "\n" for p in dev))
open(sys.argv[1] + "/src.list", "w").write("".join(p["file"] + "\n" for p in dev))
import glob, os
for f in glob.glob(sys.argv[2] + "/prerun*.jsonl"):
    rows = [l for l in open(f) if l.strip() and json.loads(l).get("id") in ids]
    open(sys.argv[1] + "/" + os.path.basename(f), "w").write("".join(rows))
' "$T/$S" "$R" || exit 1
      $SSH "$HOST" "mkdir -p $ROOT/$R/src"
      rsync -a "$T/$S/programs.jsonl" "$T/$S"/prerun*.jsonl -e "$SSH" "$HOST:$ROOT/$R/"
      rsync -a --files-from="$T/$S/src.list" -e "$SSH" $R/src/ "$HOST:$ROOT/$R/src/"
    done
    [ -f results/harvest-known/_harvest_49a.py ] &&
      rsync -a -e "$SSH" results/harvest-known/_harvest_49a.py "$HOST:$ROOT/results/harvest-known/"
    $SSH "$HOST" "mkdir -p $ROOT/results/parity $ROOT/corpus/apps"
    rsync -a -e "$SSH" results/parity/fuzz "$HOST:$ROOT/results/parity/"
    [ -d results/parity/stress-checked ] &&
      rsync -a -e "$SSH" results/parity/stress-checked "$HOST:$ROOT/results/parity/"
    for A in Kernels BabelStream XSBench RSBench miniWeather; do
      rsync -a --exclude=.git -e "$SSH" corpus/apps/$A "$HOST:$ROOT/corpus/apps/"
    done
    rm -rf "$T"
    echo "pushed to $HOST:$ROOT (dev programs only)" ;;
  pull)
    D=results/parity/$2
    mkdir -p "$D"
    for o in $OUTS; do
      $SSH "$HOST" "test -e $ROOT/$o" || continue
      mkdir -p "$D/$o"
      rsync -a --exclude=build --exclude='*.tmp' -e "$SSH" "$HOST:$ROOT/$o/" "$D/$o/"
    done
    echo "pulled into $D" ;;
  *) echo "usage: $0 push|pull wingtip|tioga"; exit 2 ;;
esac
