# Source this first in any script that runs on wingtip (a shared host, no scheduler):
#     . "$(dirname "$0")/wingtip_cap.sh" || exit 1
# It re-executes the script inside the user slice compliant.slice, whose limits (in
# ~/.config/systemd/user/compliant.slice on wingtip: MemoryHigh=96G, MemoryMax=128G,
# MemorySwapMax=0, TasksMax=2048, CPUWeight=50) bound ALL of this project's jobs together,
# so compiles and tests cannot exhaust the host's memory (the 2026-10-24 outage took
# sshd/authentication down for everyone). Lingering is enabled for the account so the
# slice outlives the ssh session. Elsewhere it does nothing.
# On wingtip (a host named wingtip*, or one with
# ~/.config/systemd/user) a missing slice file or systemd-run is an error (return 1),
# never an uncapped run. COMPLIANT_HOSTNAME overrides the host name (tests).
# One-off commands: tools/jobs/wingtip_capped.sh CMD ARGS...
if [ -z "${COMPLIANT_CAPPED:-}" ]; then
  case "${COMPLIANT_HOSTNAME:-$(hostname -s 2>/dev/null)}" in
    wingtip*) _cap_here=1 ;;
    *) [ -d "$HOME/.config/systemd/user" ] && _cap_here=1 || _cap_here= ;;
  esac
  if [ -n "$_cap_here" ]; then
    if [ ! -f "$HOME/.config/systemd/user/compliant.slice" ] || ! command -v systemd-run >/dev/null; then
      echo "wingtip_cap.sh: on wingtip but compliant.slice or systemd-run is missing: refusing to run uncapped" >&2
      return 1 2>/dev/null || exit 1
    fi
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    export COMPLIANT_CAPPED=1
    exec systemd-run --user --slice=compliant.slice --scope --quiet \
         bash "$0" "$@"
  fi
fi
