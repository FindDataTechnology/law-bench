# syntax=docker/dockerfile:1
#
# Evaluation Rules Manager (FastAPI web app) image.
# Serves `src.web.app:app` on 0.0.0.0:8010.
#
# The SQLite DB ships at /app/db/evaluation_rules.db as seed data (rubrics,
# criteria, prompts). Mount a named volume at /app/db to persist eval runs and
# rubric edits across restarts — Docker copies the seeded file into the volume
# on first use.
#
#   docker build -t law-template .
#   docker run --rm -p 8010:8010 law-template
#
# With persistence + LLM creds (needed only for drafting / evaluation, not for
# browsing rubrics):
#   docker run --rm -p 8010:8010 -v law-bench-db:/app/db \
#     -e OPENAI_API_KEY=... -e OPENAI_API_BASE=... \
#     -e INTAKE_MODEL=... -e DRAFTER_MODEL=... -e AUDITOR_MODEL=... law-template

# Global build args. Both MUST sit before the first FROM: with the legacy
# (non-BuildKit) builder an ARG only feeds a FROM line if it is declared
# before any FROM — declaring BASE_IMAGE after the node stage left it blank
# and failed the build with "base name (${BASE_IMAGE}) should not be blank".
# Admin-assistant island (CopilotKit CopilotPopup, change
# add-admin-copilot-assistant): built in a throwaway node stage and copied into
# the runtime image's static dir below, so node never ships in the runtime.
# The island bundle is ~17 MB minified (~3.8 MB gzip) — one cached download for
# admin sessions only.
ARG NODE_IMAGE=node:22-slim
ARG BASE_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim
FROM ${NODE_IMAGE} AS assistant-ui
# Default is upstream npm; the in-cluster CI builder overrides with a domestic
# mirror, same rationale as UV_INDEX_URL below.
ARG NPM_REGISTRY=https://registry.npmjs.org
RUN npm config set registry ${NPM_REGISTRY}
WORKDIR /build
COPY assistant-ui/package.json assistant-ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY assistant-ui/ ./
# Vite emits to ../src/web/static/assistant per vite.config.ts → /src/... here.
RUN npm run build

# Base image default lives in the global ARG block above; the in-cluster CI
# builder overrides BASE_IMAGE with a ghcr.io mirror because the ghcr.io blob
# CDN is unreachable from that network (its metadata endpoints resolve, but
# layer downloads stall indefinitely). See Jenkinsfile "Build".
FROM ${BASE_IMAGE}

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app

# The runtime user is created up front, so every COPY below lands already owned
# by it and every uv invocation runs as it. Doing it this way — rather than a
# trailing `chown -R appuser:appuser /app` — matters: Docker materialises an
# ownership change as a full second copy of the affected tree, so that trailing
# chown added a ~1.2 GB duplicate of the venv to the image.
RUN useradd --create-home --uid 1001 appuser \
    && chown appuser:appuser /app

# DOCX -> PDF rendering no longer lives in this image (extract-render-service):
# it moved to the shared render service (Dockerfile.render), reached at runtime
# via DOCS_PDF_BACKEND=http + RENDER_SERVICE_URL in the deploy manifests. That
# layer (libreoffice-writer + fonts-noto-cjk) was ~1.2-1.5 GB of every image.

# Package index for resolving locked deps. Default is PyPI; the in-cluster CI
# builder overrides UV_INDEX_URL with a domestic mirror because direct PyPI is
# unreachable from that network (pypi.org connections hang; a partial transfer
# once surfaced as "deflate decompression error: invalid stored block lengths").
ARG UV_INDEX_URL=https://pypi.org/simple
ENV UV_DEFAULT_INDEX=${UV_INDEX_URL}

# Keep uv's wheel cache out of the image. By default uv caches downloads under
# ~/.cache/uv, which lands in the layer and (for this dependency set) added
# ~1.2 GB. Point it at a scratch dir and drop it in the same RUN that populates
# it, so it never becomes part of an image layer. HOME is set so uv/tools resolve
# the appuser home rather than a stale /root inherited from the build stage.
ENV UV_CACHE_DIR=/tmp/uv-cache \
    HOME=/home/appuser

# Install dependencies first (cacheable layer). --no-install-project avoids
# needing a [build-system]: only the locked third-party deps are installed.
# Deliberately NOT --frozen: --frozen installs from the lockfile's recorded
# registry (pypi.org) and would ignore UV_DEFAULT_INDEX, whereas a plain sync
# resolves against the configured index while preferring the locked versions.
COPY --chown=appuser:appuser pyproject.toml uv.lock ./

USER appuser

RUN uv sync --no-install-project --no-dev \
    && rm -rf "$UV_CACHE_DIR"

# Application sources + seed data.
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser templates ./templates
COPY --chown=appuser:appuser db ./db
COPY --chown=appuser:appuser scripts ./scripts

# MCP server package (fd-coding-law-bench-mcp) into the same venv. Only its
# build inputs are staged (pyproject + src) — not the dev tree (tests/.venv).
# Its declared deps (fastmcp, langgraph, langchain-core) resolve on top of the
# locked env above and must not disturb those versions. Staged under /app
# (appuser-owned) so the cleanup can unlink it.
COPY --chown=appuser:appuser fd-coding-law-bench-mcp/pyproject.toml ./deps/lawbench-mcp/pyproject.toml
COPY --chown=appuser:appuser fd-coding-law-bench-mcp/src ./deps/lawbench-mcp/src
RUN uv pip install --python .venv ./deps/lawbench-mcp \
    && rm -rf ./deps "$UV_CACHE_DIR"

# Admin-assistant island built in the node stage above; overwrites any stale
# locally-built bundle so the shipped assets are always the image's own build.
COPY --from=assistant-ui --chown=appuser:appuser /src/web/static/assistant ./src/web/static/assistant

# Strip CR from shell scripts: checkouts on Windows carry CRLF, which breaks
# the `#!/bin/sh` shebang ("no such file or directory" at exec).
RUN find scripts -name '*.sh' -exec sed -i 's/\r$//' {} + \
    && chmod +x scripts/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8010

# Self-heal harbor rubrics from the bundled seed on every boot (harbor isn't
# installed in the image), then serve. See scripts/docker-entrypoint.sh.
CMD ["./scripts/docker-entrypoint.sh"]
