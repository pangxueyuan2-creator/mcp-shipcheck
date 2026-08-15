#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="${1:-$ROOT/.demo}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

printf '\n== 1. Capture a baseline from the real stdio server process ==\n'
"$PYTHON_BIN" -m mcp_shipcheck verify --output "$WORKDIR/baseline.json" -- \
  "$PYTHON_BIN" "$ROOT/demo/fixture_server.py" --mode baseline

printf '\n== 2. A compatible release adds one tool ==\n'
"$PYTHON_BIN" -m mcp_shipcheck verify --baseline "$WORKDIR/baseline.json" \
  --output "$WORKDIR/compatible.json" --compare-output "$WORKDIR/compatible-compare.json" -- \
  "$PYTHON_BIN" "$ROOT/demo/fixture_server.py" --mode compatible
cat "$WORKDIR/compatible-compare.json"

printf '\n== 3. A breaking release removes a tool and narrows input requirements ==\n'
set +e
"$PYTHON_BIN" -m mcp_shipcheck verify --baseline "$WORKDIR/baseline.json" \
  --output "$WORKDIR/breaking.json" --compare-output "$WORKDIR/breaking-compare.json" -- \
  "$PYTHON_BIN" "$ROOT/demo/fixture_server.py" --mode breaking
status=$?
set -e
if [[ "$status" -ne 2 ]]; then
  echo "Expected a compatibility exit code of 2, got $status" >&2
  exit 1
fi
cat "$WORKDIR/breaking-compare.json"
printf '\nDemo complete. Artifacts are in %s\n' "$WORKDIR"
