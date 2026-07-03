#!/bin/bash
cd "$(dirname "$0")"
run_one() {
  t=$1; c=$2
  [ -f "results/${t}_${c}.json" ] && { echo "SKIP $t $c"; return; }
  ../../.venv/bin/python3 run_cell.py "$t" "$c" > "results/run_${t}_${c}.log" 2>&1 \
    && echo "OK   $t $c" || echo "FAIL $t $c"
}
export -f run_one
xargs -a queue.txt -n2 -P6 bash -c 'run_one "$@"' _
echo "ALL_DONE"
