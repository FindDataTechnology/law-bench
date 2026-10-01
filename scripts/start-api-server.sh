#!/bin/bash
# Start the law-bench HTTP API server

set -e

cd "$(dirname "$0")/.."

echo "Starting law-bench HTTP API server..."

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8000}"
export DEBUG="${DEBUG:-false}"

exec uvicorn \
    fd_coding_law_bench_mcp.api.main:app \
    --host "$HOST" \
    --port "$PORT" \
    ${DEBUG:+--reload} \
    --workers 1 \
    "$@"
