#!/bin/bash
# Keep the wingtip clone (NVIDIA A100, NVHPC; catalog/machines.yaml
# `wingtip`) in step with this working tree, and bring its results back.
# wingtip has no GitHub access, so the clone is an rsync copy: the tracked
# files of this tree (as they are on disk) plus the corpora a run needs
# (corpus/omp_vv, corpus/acc_vv); nothing else (its home is a 50G NFS quota),
# and never a sealed benchmark set not yet scored (catalog/sealed_spent.yaml).
#   tools/lanes/wingtip_sync.sh push            # code + catalog + the two corpora
#   tools/lanes/wingtip_sync.sh push-results    # results/{matrix,matrix_c,acc_matrix}.jsonl
#   tools/lanes/wingtip_sync.sh pull <subdir>   # results/<subdir> back into results/
# Host and root come from the machine's access settings (catalog/machines.yaml with your local settings laid over it).
set -eu
cd "$(dirname "$0")/../.."
read -r HOST ROOT < <(python3 -I -c '
import sys; sys.path.insert(0, ".")
from offload.engine.confirm.machines import load
a = load()["wingtip"].access
if not isinstance(a, dict) or "ssh" not in a:
    sys.exit("wingtip: no ssh access set; give it in your local settings (catalog/local.example.yaml)")
print(a["ssh"], a["root"])')
SSH="ssh -o BatchMode=yes -o ControlMaster=auto -o ControlPath=$HOME/.ssh/cm-compliant-%r@%h:%p -o ControlPersist=10m"
case "${1:-}" in
  push)
    $SSH "$HOST" "mkdir -p $ROOT/results $ROOT/corpus"
    # tracked and new (not ignored) files, as on disk; the revision they
    # start from (and whether the tree differs) is recorded in .wingtip_rev
    echo "$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- . || echo +dirty) $(date -Is)" > .wingtip_rev
    # never a sealed benchmark set that is not scored yet (data/bench/<set>/SEAL
    # without <set> in catalog/sealed_spent.yaml): it stays on Tuolumne
    files=$(mktemp)
    { git ls-files -co --exclude-standard -z; printf '.wingtip_rev\0'; } |
      python3 -I tools/lanes/wingtip_offline.py code-files > "$files"
    rsync -a --from0 --files-from="$files" -e "$SSH" ./ "$HOST:$ROOT/"
    rm -f "$files"
    rm -f .wingtip_rev
    for c in omp_vv acc_vv; do
      rsync -a --delete --exclude .git -e "$SSH" "corpus/$c/" "$HOST:$ROOT/corpus/$c/"
    done
    # the spec text cache (git-ignored) is read by catalog code paths
    [ -d results/spec_cache ] && rsync -a -e "$SSH" results/spec_cache/ "$HOST:$ROOT/results/spec_cache/"
    echo "pushed to $HOST:$ROOT" ;;
  push-results)  # the merged result files the expected set is chosen from
    rsync -a -e "$SSH" results/matrix.jsonl results/matrix_c.jsonl \
      results/acc_matrix.jsonl "$HOST:$ROOT/results/"
    echo "pushed results/*matrix*.jsonl" ;;
  pull)
    sub=${2:?pull needs a results subdirectory}
    mkdir -p "results/$sub"
    rsync -a -e "$SSH" "$HOST:$ROOT/results/$sub/" "results/$sub/"
    echo "pulled results/$sub" ;;
  *) echo "usage: $0 push | push-results | pull <results subdir>"; exit 2 ;;
esac
