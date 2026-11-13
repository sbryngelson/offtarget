#!/bin/bash
# Fake compiler for tests/engine/test_findings_nogpu.py, used as Toolchain.fc:
#   fake_fc.sh <message-file|-> <exit-status> <executable|-> <flags...> <src> -o <out>
# Prints the verbatim part of a captured real message file (the text after
# the "==== verbatim output below ====" line) to stderr, copies <executable>
# to <out> (a fake program, see exe_*.sh), and exits with <exit-status>.
msg=$1; rc=$2; exe=$3; shift 3
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then out=$2; shift; fi
  shift
done
if [ "$msg" != "-" ]; then
  sed '1,/^==== verbatim output below ====$/d' "$msg" >&2
fi
if [ "$exe" != "-" ]; then
  cp "$exe" "$out" && chmod +x "$out"
fi
exit "$rc"
