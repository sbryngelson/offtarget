#!/bin/bash
# Run one CPU-only step on wingtip instead of a Tuolumne batch
# job (docs/tooling/wingtip.md, "Offline lane"). From this tree (a worktree or the
# main tree) on a Tuolumne login node:
#   tools/lanes/wingtip_offline.sh --list
#   tools/lanes/wingtip_offline.sh --dry-run STEP [ARGS...]   # the plan; no ssh
#   tools/lanes/wingtip_offline.sh [--trace] [--env K=V]... STEP [ARGS...]
#   tools/lanes/wingtip_offline.sh --no-pull STEP ...         # leave the outputs there
#   tools/lanes/wingtip_offline.sh --setup                    # the Python env, once
# It (1) refuses unless wingtip has compliant.slice and systemd-run (and
# the lane's Python environment); (2) copies this tree's code (tracked and
# new files as on disk, without any sealed benchmark set not yet scored in
# catalog/sealed_spent.yaml, and its HEAD commit as a git bundle) to the lane
# LANES/<name of this tree> in wingtip's home, and exactly the inputs the
# step names in tools/lanes/wingtip_offline.yaml: those under results/, corpus/
# and spec/ to the shared data directory on /fastscratch (the lane links
# to it); (3) runs the step there through tools/lanes/wingtip_offline_run.sh
# (inside compliant.slice, nice, `timeout --kill-after=10 LIMIT`); (4) on
# success copies the step's outputs back to where the Tuolumne step
# writes them (results/ outputs into results/, the others into this
# tree). The log is results/offline/<step>.<lane>.<time>.log.
# Every remote command is bounded by `timeout`. WINGTIP_LANE names the
# lane; WINGTIP_OFFLINE_SSH and WINGTIP_OFFLINE_RSYNC replace ssh and
# rsync (tests). Exit: the step's status; 1 refused; 2 usage; 4 a --trace
# run found inputs the manifest does not name.
# On Tuolumne the cap is a no-op; on wingtip itself this would run capped.
. "$(dirname "$0")/../jobs/wingtip_cap.sh" || exit 1
set -u
cd "$(dirname "$0")/../.." || exit 1
TOP=$(pwd -P)
PYL=${WINGTIP_OFFLINE_PY:-python3}
MAN="$PYL -I tools/lanes/wingtip_offline.py"
read -r HOST DATA LANES < <($PYL -I -c '
import sys; sys.path.insert(0, "tools/lanes")
import wingtip_offline as W; m = W.load()
print(m["host"], m["data_root"], m["lane_root"])') || exit 2
DATA=${WINGTIP_OFFLINE_DATA:-$DATA}
LANE_NAME=${WINGTIP_LANE:-$(basename "$TOP")}
case "$LANE_NAME" in ''|*/*|.*|*' '*) echo "bad lane name $LANE_NAME" >&2; exit 2 ;; esac
LANE=$LANES/$LANE_NAME
SSHOPT="-o BatchMode=yes -o LogLevel=error -o ConnectTimeout=30 -o ControlMaster=auto -o ControlPath=$HOME/.ssh/cm-compliant-%r@%h:%p -o ControlPersist=10m"
SSH=${WINGTIP_OFFLINE_SSH:-ssh $SSHOPT}
RSYNC=${WINGTIP_OFFLINE_RSYNC:-rsync}
RUN="WINGTIP_OFFLINE_DATA=$DATA bash $LANE/tools/lanes/wingtip_offline_run.sh"

DRY= TRACE= SETUP= NOPULL=
ENVS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --list) exec $MAN list ;;
    --dry-run) DRY=1; shift ;;
    --trace) TRACE=--trace; shift ;;
    --setup) SETUP=1; shift ;;
    --no-pull) NOPULL=1; shift ;;
    --env) [ $# -ge 2 ] || exit 2; ENVS+=(--env "$2"); shift 2 ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
if [ -z "$SETUP" ]; then
  [ $# -ge 1 ] || { echo "usage: $0 [--dry-run] [--trace] [--env K=V]... STEP [ARGS...]" >&2; exit 2; }
  STEP=$1; shift
  $MAN shell "$STEP" > /dev/null || exit 2
fi

T=$(mktemp -d "${TMPDIR:-/tmp}/wingtip-offline.XXXXXX") || exit 1
trap 'rm -rf "$T"' EXIT

# the code: tracked and new files as on disk, never the shared links
# and never a sealed benchmark set that is not scored yet
# (catalog/sealed_spent.yaml)
git ls-files -co --exclude-standard -z |
  grep -zvE '^(results|corpus|spec)(/|$)' | $MAN code-files > "$T/code.list" ||
  { echo "listing the code failed" >&2; exit 1; }
[ -n "${STEP:-}" ] && $MAN inputs "$STEP" --under code >> "$T/code.list"
echo "$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- . || echo +dirty) $(date -Is)" > "$T/rev"

if [ -n "$DRY" ]; then
  $MAN plan "$STEP" "$@"; prc=$?
  echo "lane     $HOST:$LANE (code: $(tr -cd '\0' < "$T/code.list" | wc -c) files, $(cat "$T/rev"))"
  for d in results corpus spec; do
    n=$($MAN inputs "$STEP" --under $d 2>/dev/null | tr -cd '\0' | wc -c)
    [ "$n" -gt 0 ] && echo "data     $n inputs -> $HOST:$DATA/$d/"
  done
  echo "run      ssh $HOST $RUN ${TRACE:+$TRACE }${ENVS[*]+${ENVS[*]} }$STEP $*"
  echo "pull     the existing outputs, after a successful run"
  echo "dry run: nothing copied or run"
  exit $prc
fi

if [ -n "${STEP:-}" ]; then
  miss=$($MAN plan "$STEP" | grep '^  MISSING')
  [ -z "$miss" ] || { echo "$miss" >&2
    echo "refused: inputs of $STEP are missing in this tree" >&2; exit 1; }
fi

# (1) the cap and the environment, before anything is copied
pre=$(timeout 120 $SSH "$HOST" "test -f ~/.config/systemd/user/compliant.slice && command -v systemd-run >/dev/null && echo CAP_OK; test -x $DATA/env/bin/python && echo ENV_OK" 2>&1)
case "$pre" in
  *CAP_OK*) ;;
  *) echo "refused: $HOST has no compliant.slice or systemd-run (docs/tooling/wingtip.md);" \
       "nothing copied or run. ($pre)" >&2; exit 1 ;;
esac
if [ -z "$SETUP" ] && [[ "$pre" != *ENV_OK* ]]; then
  echo "refused: no Python environment at $HOST:$DATA/env; run $0 --setup" >&2; exit 1
fi

# (2) the code, its commit, the inputs
timeout 120 $SSH "$HOST" "mkdir -p $LANE/.offline $DATA/results $DATA/corpus $DATA/spec" || exit 1
remote_head=$(timeout 60 $SSH "$HOST" "git -C $LANE rev-parse HEAD 2>/dev/null" 2>/dev/null)
if [ "$remote_head" != "$(git rev-parse HEAD)" ]; then
  git bundle create -q "$T/head.bundle" HEAD || exit 1
  timeout 600 $RSYNC -a -e "$SSH" "$T/head.bundle" "$HOST:$LANE/.offline/head.bundle" || exit 1
fi
cp "$T/rev" "$T/.wingtip_rev"
timeout 1800 $RSYNC -a --from0 --files-from="$T/code.list" -e "$SSH" ./ "$HOST:$LANE/" &&
  timeout 120 $RSYNC -a -e "$SSH" "$T/.wingtip_rev" "$HOST:$LANE/.wingtip_rev" &&
  timeout 120 $RSYNC -a -e "$SSH" "$T/code.list" "$HOST:$LANE/.offline/files.list" || {
  echo "copying the code to $HOST:$LANE failed" >&2; exit 1; }
timeout 300 $SSH "$HOST" "$RUN --prepare" || { echo "preparing $HOST:$LANE failed" >&2; exit 1; }
if [ -n "$SETUP" ]; then
  timeout 2000 $SSH "$HOST" "$RUN --setup"; exit $?
fi
for d in results corpus spec; do
  $MAN inputs "$STEP" --under $d > "$T/$d.list" || exit 1
  [ -s "$T/$d.list" ] || continue
  t0=$(date +%s)
  timeout 3600 $RSYNC -a -r --delete --copy-unsafe-links --from0 --files-from="$T/$d.list" \
    -e "$SSH" "$d/" "$HOST:$DATA/$d/" || { echo "copying the $d inputs failed" >&2; exit 1; }
  echo "copied $(tr -cd '\0' < "$T/$d.list" | wc -c) $d inputs in $(( $(date +%s) - t0 )) s"
done

# (3) the step
eval "$($MAN shell "$STEP")"
mkdir -p results/offline
LOG=results/offline/$STEP.$LANE_NAME.$(date +%Y%m%dT%H%M%S).log
args=""
for x in "$@"; do args+=" $(printf '%q' "$x")"; done
envs=""
for x in ${ENVS[@]+"${ENVS[@]}"}; do envs+=" $(printf '%q' "$x")"; done
t0=$(date +%s)
timeout $(( LIMIT + 300 )) $SSH "$HOST" "$RUN $TRACE$envs $STEP$args" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
echo "wingtip_offline: $STEP exit $rc after $(( $(date +%s) - t0 )) s (with the copies); log $LOG" | tee -a "$LOG"

if [ -n "$TRACE" ]; then
  # the manifest's gaps, judged against this tree
  if timeout 120 $RSYNC -a -e "$SSH" "$HOST:$LANE/.offline/trace-report.json" "$T/report.json"; then
    $MAN trace-gaps "$T/report.json" | tee -a "$LOG"
    if [ "${PIPESTATUS[0]}" -ne 0 ]; then
      echo "wingtip_offline: the manifest of $STEP misses inputs (exit 4)" | tee -a "$LOG" >&2
      [ "$rc" -ne 0 ] || rc=4
    fi
  fi
fi

# (4) the outputs
if [ "$rc" -ne 0 ]; then
  echo "wingtip_offline: $STEP failed; outputs left on $HOST (not copied back)" | tee -a "$LOG" >&2
  exit "$rc"
fi
if [ -n "$NOPULL" ]; then
  echo "wingtip_offline: --no-pull: outputs left in $HOST:$LANE and $HOST:$DATA" | tee -a "$LOG"
  exit 0
fi
timeout 120 $RSYNC -a -e "$SSH" "$HOST:$LANE/.offline/outputs.list" "$T/outputs.list" || exit 1
for d in results corpus spec code; do : > "$T/out.$d"; done
while IFS= read -r -d '' p; do
  case "$p" in
    results/*|corpus/*|spec/*) printf '%s\0' "${p#*/}" >> "$T/out.${p%%/*}" ;;
    *) printf '%s\0' "$p" >> "$T/out.code" ;;
  esac
done < "$T/outputs.list"
for d in results corpus spec; do
  [ -s "$T/out.$d" ] || continue
  timeout 3600 $RSYNC -a -r -K --from0 --files-from="$T/out.$d" -e "$SSH" \
    "$HOST:$DATA/$d/" "$d/" || { echo "copying $d outputs back failed" >&2; exit 1; }
done
if [ -s "$T/out.code" ]; then
  timeout 600 $RSYNC -a -r -K --from0 --files-from="$T/out.code" -e "$SSH" \
    "$HOST:$LANE/" ./ || { echo "copying outputs back failed" >&2; exit 1; }
fi
echo "wingtip_offline: copied back: $(tr '\0' ' ' < "$T/outputs.list")" | tee -a "$LOG"
exit 0
