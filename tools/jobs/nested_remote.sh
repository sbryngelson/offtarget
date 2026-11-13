#!/bin/bash
# nested-data (tools/campaigns/nested.py): a private copy of this tree on wingtip or
# Tioga, and the results back.
#   tools/jobs/nested_remote.sh push wingtip|tioga [NAME]
#   tools/jobs/nested_remote.sh pull wingtip|tioga [NAME]   # rows and gate reruns -> results/nested/NAME/
# The copy: tracked and new files as on disk (less the sealed unscored sets,
# tools/lanes/wingtip_offline.py code-files) and results/nested/NAME/{meta.json,
# programs.jsonl, src/, prerun parts}: the stored legality verdicts, which
# neither machine can compute (they need AFAR's front end). Roots:
# <campaign_lanes of the machine>/nested-lane (wingtip) and /wt-nested (Tioga).
# Run there with PY set to that machine's Python (its access.python); tools/jobs/run_wingtip_nested.sh and
# tools/jobs/run_nested_tioga.sh are the entry points.
set -eu
cd "$(dirname "$0")/../.."
NAME=${3:-main}
case "${2:-}" in
  tioga) HOST=${HOST:-tio}; ROOT=$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import registry; print(registry().campaign_lanes["tioga"])')/wt-nested
         SSH="ssh -o BatchMode=yes" ;;
  wingtip) HOST=${HOST:-wingtip}; ROOT=$(python3 -I -c 'import sys; sys.path.insert(0, "."); from offload.engine.toolchains import registry; print(registry().campaign_lanes["wingtip"])')/nested-lane
           SSH="ssh -o BatchMode=yes -o ControlMaster=auto -o ControlPath=$HOME/.ssh/cm-compliant-%r@%h:%p -o ControlPersist=10m" ;;
  *) echo "usage: $0 push|pull wingtip|tioga [NAME]"; exit 2 ;;
esac
case "$1" in
  push)
    $SSH "$HOST" "mkdir -p $ROOT/results/nested/$NAME"
    T=$(mktemp -d "${TMPDIR:-/tmp}/nestedpush.XXXXXX") || exit 1
    git ls-files -co --exclude-standard -z | grep -zv -E "^(results|corpus|spec)$" |
      grep -zv -E "^data/bench/[^/]*holdout" |
      python3 -I tools/lanes/wingtip_offline.py code-files > "$T/code.list" || exit 1
    rsync -a --from0 --files-from="$T/code.list" -e "$SSH" ./ "$HOST:$ROOT/"
    git rev-parse --short HEAD > "$T/rev"
    rsync -a -e "$SSH" "$T/rev" "$HOST:$ROOT/.wingtip_rev"
    D=results/nested/$NAME
    rsync -a -e "$SSH" "$D/meta.json" "$D/programs.jsonl" "$D/src" \
      "$HOST:$ROOT/$D/"
    rsync -a -e "$SSH" $D/prerun*.jsonl "$HOST:$ROOT/$D/"
    # WITH_ROWS=1: the other machines' rows and reruns too, so that the gate
    # plans here as it plans everywhere (one plan over every machine's rows)
    [ -z "${WITH_ROWS:-}" ] || rsync -a -e "$SSH" $D/rows.part.*.jsonl \
      $D/gate_reruns.part.*.jsonl "$HOST:$ROOT/$D/"
    rm -rf "$T"
    echo "pushed to $HOST:$ROOT" ;;
  pull)
    D=results/nested/$NAME
    mkdir -p "$D"
    rsync -a -e "$SSH" --include='rows*.jsonl' --include='gate_reruns*.jsonl' \
      --exclude='*' "$HOST:$ROOT/results/nested/$NAME/" "$D/"
    echo "pulled $D" ;;
esac
