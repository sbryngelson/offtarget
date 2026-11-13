#!/bin/bash
# Run one command on wingtip inside the capped user slice (see tools/jobs/wingtip_cap.sh).
#     tools/jobs/wingtip_capped.sh make -j2
# Off wingtip, or already inside the slice, it runs the command as is. On wingtip (a host
# named wingtip*, or one with ~/.config/systemd/user) a missing slice file or systemd-run is
# an error (exit 1), never an uncapped run.
set -e
[ $# -ge 1 ] || { echo "usage: $0 CMD [ARGS...]" >&2; exit 2; }
if [ -n "${COMPLIANT_CAPPED:-}" ]; then
  exec "$@"
fi
case "${COMPLIANT_HOSTNAME:-$(hostname -s 2>/dev/null)}" in
  wingtip*) here=1 ;;
  *) if [ -d "$HOME/.config/systemd/user" ]; then here=1; else here=; fi ;;
esac
if [ -z "$here" ]; then
  exec "$@"
fi
if [ ! -f "$HOME/.config/systemd/user/compliant.slice" ] || ! command -v systemd-run >/dev/null; then
  echo "wingtip_capped.sh: on wingtip but compliant.slice or systemd-run is missing: refusing to run uncapped" >&2
  exit 1
fi
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" COMPLIANT_CAPPED=1
exec systemd-run --user --slice=compliant.slice --scope --quiet "$@"
