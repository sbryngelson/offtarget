#!/bin/bash
# One wingtip stream: run_wingtip.sh for several environments in order on one GPU.
#   setsid nohup ~/t44/checks/wt_stream.sh GPU "a:nvidia:repro,control a:-:repro b:nvidia:repro,control" > log 2>&1 &
cd "$(dirname "$0")" || exit 1
G=$1
for item in $2; do
  IFS=: read -r E VEN V <<< "$item"
  [ "$VEN" = "-" ] && VEN=""
  ./run_wingtip.sh "$E" "$G" - "$V" "$VEN" || echo "stream item $item failed"
done
echo "stream done $(date -Is)"
