#!/bin/bash
cd "$(dirname "$0")/../../.." || exit 1
python3 -I tools/repo/check_citations.py data/findings/malloc/afar-device-malloc-in-kernel-corrupts-records.c
python3 -I tools/repo/check_findings.py malloc/afar-device-malloc-in-kernel-corrupts-records.c
python3 -I tools/repo/check_findings.py --summary | tail -5
echo finished
