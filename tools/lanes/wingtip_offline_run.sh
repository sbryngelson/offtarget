#!/bin/bash
# The wingtip half of the offline lane. tools/lanes/wingtip_offline.sh
# (on Tuolumne) copies the code and a step's inputs, then runs this over
# ssh; it runs on wingtip, inside compliant.slice (it stops when the cap
# is missing), under nice and `timeout --kill-after=10 LIMIT` (the step's
# limit in tools/lanes/wingtip_offline.yaml), with the lane's Python
# environment first on PATH. docs/tooling/wingtip.md, "Offline lane".
#   wingtip_offline_run.sh --prepare             # links, git HEAD, prune
#   wingtip_offline_run.sh --setup               # the Python environment
#   wingtip_offline_run.sh [--trace] [--env K=V]... STEP [ARGS...]
# WINGTIP_OFFLINE_DATA is the shared data directory (results/, corpus/,
# spec/ and env/ of the lane live there). Every run records the programs
# the step executes (strace, execve only) and fails with 3 when it tried
# one wingtip does not have. Exit: the step's status (124: its time
# limit), 3 that guard, 75 when the lane is busy, 1-3 when it did not
# start.
. "$(dirname "$0")/../jobs/wingtip_cap.sh" || exit 1
set -u
LANE=$(cd "$(dirname "$0")/../.." && pwd -P) || exit 1
DATA=${WINGTIP_OFFLINE_DATA:?WINGTIP_OFFLINE_DATA is not set}
PY=$DATA/env/bin/python
cd "$LANE" || exit 1
mkdir -p .offline

prepare() {
  local d
  for d in results corpus spec; do
    mkdir -p "$DATA/$d"
    if [ -e "$d" ] && [ ! -L "$d" ]; then
      echo "lane $LANE: $d is not a link to $DATA/$d" >&2; return 1
    fi
    ln -sfn "$DATA/$d" "$d"
  done
  # the commit the copy was made from: git rev-parse and diff work in it
  if [ -f .offline/head.bundle ]; then
    [ -d .git ] || git init -q . || return 1
    git fetch -q .offline/head.bundle HEAD &&
      git update-ref refs/heads/offline FETCH_HEAD &&
      git symbolic-ref HEAD refs/heads/offline &&
      git read-tree HEAD || return 1
    rm -f .offline/head.bundle
  fi
  # files of earlier copies that are no longer in the tree
  if [ -f .offline/files.list ] && [ -x "$PY" ]; then
    "$PY" -I - <<'EOF'
import os
keep = set(open(".offline/files.list", "rb").read().decode().split("\0"))
top = {".offline", ".git", "results", "corpus", "spec"}
for d, dirs, files in os.walk("."):
    rel = os.path.relpath(d, ".")
    dirs[:] = [x for x in dirs if not (rel == "." and x in top)
               and x not in ("__pycache__", ".pytest_cache")]
    for f in files:
        p = os.path.normpath(os.path.join(rel, f))
        if p not in keep and p != ".wingtip_rev":
            os.remove(p)
            print("pruned", p)
EOF
  fi
}

case "${1:-}" in
  --prepare) prepare; exit $? ;;
  --setup)
    # Python as on Tuolumne (3.13.2, PyYAML 6.0.2, numpy 2.1.2, scipy
    # 1.15.3) with the test packages of tools/repo/test_requirements.txt
    # (pytest 9.0.3 or later: GHSA-6w46-j5rx-g56g), in the shared data
    # directory; an existing env with other versions is brought to these
    PINS="PyYAML==6.0.2 numpy==2.1.2 scipy==1.15.3 pytest==9.1.1 pluggy==1.7.0 pytest-xdist==3.8.0 hatchling==1.33.0 hatch-vcs==0.5.0 setuptools-scm==10.3.4 setuptools==84.2.1"
    if [ -x "$PY" ] && "$PY" - $PINS <<'EOF'
import sys
from importlib.metadata import version, PackageNotFoundError
def have(name, want):
    try:
        return version(name) == want
    except PackageNotFoundError:
        return False
sys.exit(0 if all(have(*p.split("==")) for p in sys.argv[1:]) else 1)
EOF
    then
      echo "env ok: $PY"; exit 0
    fi
    if [ ! -x "$PY" ]; then
      MM=${MICROMAMBA:-micromamba}
      nice -n 10 timeout --kill-after=10 900 "$MM" create -y -q -p "$DATA/env" \
        -c conda-forge --override-channels python=3.13.2 pip || exit 3
    fi
    # shellcheck disable=SC2086
    nice -n 10 timeout --kill-after=10 900 "$PY" -m pip install -q $PINS || exit 3
    exit 0 ;;
esac

TRACE=
ENVS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --trace) TRACE=1; shift ;;
    --env) ENVS+=("$2"); shift 2 ;;
    --) shift; break ;;
    -*) echo "usage: $0 [--trace] [--env K=V]... STEP [ARGS...]" >&2; exit 2 ;;
    *) break ;;
  esac
done
STEP=${1:?usage: $0 [--trace] [--env K=V]... STEP [ARGS...]}
shift
[ -x "$PY" ] || { echo "no Python environment at $DATA/env" \
  "(tools/lanes/wingtip_offline.sh --setup)" >&2; exit 3; }
export PATH="$DATA/env/bin:$PATH" COMPLIANT_ROOT="$LANE"
exec 9>>.offline/lock
flock -w 30 9 || { echo "lane $LANE is busy (another offline step runs in it)" >&2
                   exit 75; }
LIMIT= GUARD= ENV_OK= CMD=()
eval "$("$PY" -I tools/lanes/wingtip_offline.py shell "$STEP")" || exit 2
for kv in ${ENVS[@]+"${ENVS[@]}"}; do
  case " $ENV_OK " in
    *" ${kv%%=*} "*) export "$kv" ;;
    *) echo "step $STEP does not take ${kv%%=*} (it takes: ${ENV_OK:-nothing})" >&2
       exit 2 ;;
  esac
done
# the guard: every program the step runs is recorded (execve only, through
# seccomp: cheap), so a step that tries to run what wingtip does not have
# (AFAR, CCE, /usr/tce) fails here instead of degrading silently
rm -rf .offline/trace && mkdir -p .offline/trace
PRE=()
if [ -n "$TRACE" ]; then
  PRE=(strace -ff -qq -s 1024 -e trace=%file,clone,clone3,fork,vfork -o .offline/trace/t)
elif [ "$GUARD" = 1 ]; then
  if [ "$(awk '/^TracerPid:/ {print $2}' /proc/self/status)" != 0 ]; then
    echo "already traced (a --trace run above this one): no exec guard of its own"
  elif ! command -v strace > /dev/null; then
    [ -n "${WINGTIP_OFFLINE_NO_GUARD:-}" ] || {
      echo "no strace for the exec guard (WINGTIP_OFFLINE_NO_GUARD=1 runs without it)" >&2; exit 3; }
  else
    PRE=(strace -f --seccomp-bpf -qq -e trace=execve -e signal=none -o .offline/trace/exec)
  fi
fi
rm -f .offline/outputs.list
echo "offline step $STEP on $(hostname -s), lane $LANE, data $DATA"
echo "cgroup $(tail -1 /proc/self/cgroup | cut -d: -f3); limit ${LIMIT} s;" \
  "git $(git rev-parse --short HEAD 2>/dev/null)$(git diff --quiet HEAD -- . 2>/dev/null || echo +dirty)"
echo "start $(date -Is): ${CMD[*]} $*"
T0=$(date +%s)
nice -n 10 timeout --kill-after=10 "$LIMIT" ${PRE[@]+"${PRE[@]}"} "${CMD[@]}" "$@"
rc=$?
echo "exit $rc after $(( $(date +%s) - T0 )) s at $(date -Is)"
if [ -n "${PRE[*]}" ]; then
  if ! "$PY" -I tools/lanes/wingtip_offline.py exec-check .offline/trace >&2 &&
     [ "$GUARD" = 1 ] && [ "$rc" = 0 ]; then
    echo "the step ran a compiler or tried a program wingtip does not have: it belongs on Tuolumne (exit 3)" >&2
    rc=3
  fi
fi
"$PY" -I tools/lanes/wingtip_offline.py outputs "$STEP" --existing > .offline/outputs.list
if [ -n "$TRACE" ]; then
  "$PY" -I tools/lanes/wingtip_offline.py trace-report "$STEP" .offline/trace \
    --root "$LANE" --data "$DATA" > .offline/trace-report.json
  echo "trace report (.offline/trace-report.json):"
  cat .offline/trace-report.json
fi
exit $rc
