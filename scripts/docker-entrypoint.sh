#!/bin/sh
# Container entrypoint: serve either the origin app or the public read-only app
# from the same image, selected by the PUBLIC_API env var.
#
# Origin (default, PUBLIC_API unset/0): self-heal harbor rubrics from the
# bundled seed at /app/db/evaluation_rules.db, then serve the full app
# (src.web.app:app) on 0.0.0.0:8010. Harbor is not installed in this image (it
# is a local `uv tool` only), so a stale PVC seeded before harbor extraction ever
# ran would otherwise hide harbor's rubrics forever. `src.eval.harbor_seed` falls
# back to a bundled seed copy of harbor's rubric TOMLs shipped in the image, so
# this restores them idempotently on every boot. The heal is scoped to
# `source LIKE 'harbor:%'` rows; local rubrics and evaluation-run data are
# never touched.
#
# Public pod (PUBLIC_API=1): serve the China-facing read-only app
# (src.web.public_app:app) instead. The harbor self-heal is SKIPPED because the
# public pod has no bundled SQLite seed — it reads from a replicated Postgres,
# so harbor rubric rows arrive via logical replication, not from /app/db. (See
# docs/public-api-deploy.md for the replication setup.)
set -e

if [ "${PUBLIC_API:-0}" = "1" ]; then
    exec .venv/bin/uvicorn src.web.public_app:app --host 0.0.0.0 --port 8010 --proxy-headers --forwarded-allow-ips='*'
fi

.venv/bin/python -m src.eval.harbor_seed --db /app/db/evaluation_rules.db

exec .venv/bin/uvicorn src.web.app:app --host 0.0.0.0 --port 8010 --proxy-headers --forwarded-allow-ips='*'
