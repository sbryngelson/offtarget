#!/bin/bash
cd "$(dirname "$0")/../../.." || exit 1
python3 -I tools/campaigns/kbody.py gen --name red1 --kind cfgs --cfgs .superpowers/kbody/red1.json || exit 1
export KB_RUN_ARGS='--toolchains afar --modes 1 --repeats 6'
tools/run_kbody.sh 'prerun run' red1 1800 8
