#!/bin/sh
# Offline maintenance run. NIGHTLY_DRY=1 only prints the commands.
set -u
cd "$(dirname "$0")/.." || exit 1
D=$(date +%Y%m%d); L=logs/nightly-$D.log; F=0
step() {
  if [ "${NIGHTLY_DRY:-}" = 1 ]; then echo "$1"; return; fi
  mkdir -p logs research
  echo "== $1" >>"$L"
  sh -c "$1" >>"$L" 2>&1 || F=$((F + 1))
}
step ".venv/bin/python eval/build_catalog.py"
step "$HOME/.claude/scripts/with-env NIM_1 NIM_2 NIM_3 -- .venv/bin/python eval/shadow_enrich.py --limit 500"
step ".venv/bin/python eval/librarian.py"
step ".venv/bin/python -m backbone.hook_log report --json > research/nightly-report-$D.json"
echo "nightly done: $F failed"
