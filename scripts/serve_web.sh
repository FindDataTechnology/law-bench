#!/usr/bin/env bash
# Serve the evaluation-rules management web app locally (loopback only).
#
# Usage:
#   bash scripts/serve_web.sh
#   RULES_WEB_PORT=8088 bash scripts/serve_web.sh
#
# The app reads/writes db/evaluation_rules.db (the same SQLite file the eval
# pipeline uses). Harbor re-extraction from the UI shells out to
# scripts/extract_harbor_rules.py, so harbor must be installed
# (`uv tool install harbor`) for that one button to work.
set -euo pipefail

PORT="${RULES_WEB_PORT:-8010}"

exec uv run uvicorn src.web.app:app --reload --host 127.0.0.1 --port "$PORT"
