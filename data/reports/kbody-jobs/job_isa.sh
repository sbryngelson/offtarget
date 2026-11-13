#!/bin/bash
# fresh -save-temps build of thresh.c with AFAR and the analysis of the flat atomics of the device image (compile only, no GPU run)
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
export TMPDIR=/tmp/${USER}_isa_$$
mkdir -p "$TMPDIR"
timeout -k 10 600 python3 -I tools/campaigns/malloc_dd.py isa
rm -rf "$TMPDIR"
echo finished
