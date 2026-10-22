#!/usr/bin/env bash
# Verify the Scout Intent engine three ways:
#   1. Meterless's official Scout eval harness (engines/scout-intent/evals) against scout/index.js
#   2. RefundWise's own held-out regression set
#   3. Feature tests (routing, injection block, clarification, signed contracts)
# Usage: bash scripts/run_scout_evals.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${METERLESS_DIR:-$HOME/meterless}"

echo "== 1. Official Meterless Scout eval harness =="
[ -d "$DIR" ] || git clone --depth 1 https://github.com/Meterless/Meterless.git "$DIR"
( cd "$DIR/engines/scout-intent" && npm install --silent && SCOUT_IMPL="$ROOT/scout/index.js" npm run evals )
cp "$DIR/engines/scout-intent/evals/reports/latest.md" "$ROOT/scout/evals/reports/meterless-official-latest.md"

echo; echo "== 2. RefundWise regression set =="
node "$ROOT/scout/evals/run.mjs"

echo; echo "== 3. Feature tests =="
node --test "$ROOT/scout/test/scout.test.mjs"
