#!/bin/bash
# the device images of thresh.c linked against stock, unmodified, release and release+acquire libc (compile only, no GPU)
ulimit -c 0
cd "$(dirname "$0")/../../.." || exit 1
export TMPDIR=/tmp/${USER}_libcimg_$$
mkdir -p "$TMPDIR"
timeout -k 10 900 python3 -I tools/campaigns/malloc_dd.py libc --image-only
rm -rf "$TMPDIR"
echo finished
