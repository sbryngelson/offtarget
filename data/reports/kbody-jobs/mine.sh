#!/bin/bash
cd "$(dirname "$0")/../../.." || exit 1
python3 -I tools/kernel_idioms.py mine
python3 -I tools/kernel_idioms.py coverage
python3 -I tools/kernel_idioms.py table --groups > results/kernel-idioms/table-groups.md
python3 -I tools/kernel_idioms.py table > results/kernel-idioms/table-tags.md
echo finished
