#!/bin/bash
# A registered campaign's private copy of this tree on wingtip or Tioga, and
# the results back (generalizes tools/jobs/nested_remote.sh, which stays as the
# record of the nested runs). The copy's root comes from catalog/toolchains.yaml
# (`campaign_lanes`; `tools/campaign.py CAMPAIGN lane MACHINE` prints it).
#   tools/jobs/campaign_remote.sh push wingtip|tioga CAMPAIGN [NAME]
#   tools/jobs/campaign_remote.sh pull wingtip|tioga CAMPAIGN [NAME]   # rows and gate reruns -> results/CAMPAIGN/NAME/
# The copy: tracked and new files as on disk (less the sealed unscored sets,
# tools/lanes/wingtip_offline.py code-files) and results/CAMPAIGN/NAME/{meta.json,
# programs.jsonl, src/, prerun parts}: the stored legality verdicts, which
# neither machine can compute (they need AFAR's front end). Run there with
# tools/jobs/run_wingtip_campaign.sh (wingtip) or tools/jobs/run_campaign.sh (Tioga,
# MACHINE=tioga PY=/usr/tce/bin/python3).
set -eu
cd "$(dirname "$0")/../.."
CAMP=${3:?usage: $0 push|pull wingtip|tioga CAMPAIGN [NAME]}
NAME=${4:-main}
ROOT=$(python3 -I tools/campaign.py "$CAMP" lane "${2:-}") || exit 2
case "${2:-}" in
  tioga) HOST=tio; SSH="ssh -o BatchMode=yes" ;;
  wingtip) HOST=wingtip
           SSH="ssh -o BatchMode=yes -o ControlMaster=auto -o ControlPath=$HOME/.ssh/cm-compliant-%r@%h:%p -o ControlPersist=10m" ;;
  *) echo "usage: $0 push|pull wingtip|tioga CAMPAIGN [NAME]"; exit 2 ;;
esac
D=results/$CAMP/$NAME
case "$1" in
  push)
    $SSH "$HOST" "mkdir -p $ROOT/$D $ROOT/results/$CAMP/logs"
    T=$(mktemp -d "${TMPDIR:-/tmp}/campaignpush.XXXXXX") || exit 1
    git ls-files -co --exclude-standard -z | grep -zv -E "^(results|corpus|spec)$" |
      grep -zv -E "^data/bench/[^/]*holdout" |
      python3 -I tools/lanes/wingtip_offline.py code-files > "$T/code.list" || exit 1
    rsync -a --from0 --files-from="$T/code.list" -e "$SSH" ./ "$HOST:$ROOT/"
    git rev-parse --short HEAD > "$T/rev"
    rsync -a -e "$SSH" "$T/rev" "$HOST:$ROOT/.wingtip_rev"
    [ -f "$D/meta.json" ] && rsync -a -e "$SSH" "$D/meta.json" "$HOST:$ROOT/$D/"
    rsync -a -e "$SSH" "$D/programs.jsonl" "$D/src" "$HOST:$ROOT/$D/"
    # a run without a stored pre-run (the rules witness then runs in place)
    for f in "$D"/prerun*.jsonl; do
      [ -e "$f" ] || continue
      rsync -a -e "$SSH" "$f" "$HOST:$ROOT/$D/"
    done
    # WITH_ROWS=1: the other machines' rows and reruns too, so that the gate
    # plans here as it plans everywhere (one plan over every machine's rows)
    [ -z "${WITH_ROWS:-}" ] || rsync -a -e "$SSH" "$D"/rows.part.*.jsonl \
      "$D"/gate_reruns.part.*.jsonl "$HOST:$ROOT/$D/"
    rm -rf "$T"
    echo "pushed to $HOST:$ROOT" ;;
  pull)
    mkdir -p "$D"
    rsync -a -e "$SSH" --include='rows*.jsonl' --include='gate_reruns*.jsonl' \
      --exclude='*' "$HOST:$ROOT/$D/" "$D/"
    echo "pulled $D" ;;
  *) echo "usage: $0 push|pull wingtip|tioga CAMPAIGN [NAME]"; exit 2 ;;
esac
