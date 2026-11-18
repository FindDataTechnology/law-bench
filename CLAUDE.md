# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

law-bench — an internal workbench for drafting and benchmarking **Chinese legal contracts** (PRC law, simplified Chinese content) with LLMs. It assembles contracts from a curated, statute-grounded clause corpus, judges drafts against rubrics with an LLM judge, self-heals low-scoring drafts, and compares drafting prompts head-to-head. Evaluation state lives in Postgres, artifacts in RustFS (S3-compatible; config keeps the `minio_*` env names), clause RAG retrieval in Elasticsearch. LLMs are accessed through an OpenAI-compatible Ark (Volcengine) endpoint configured via `.env` (copy `.env.example`).

## Repo layout — three deployables

1. **Root package + web UI** (`src/`, `main.py`, `scripts/`): the core. FastAPI + Jinja2 login-gated workbench (`src/web/app.py`), a public-API FastAPI app (`src/web/public_app.py`), eval/rubric/compare/pipeline logic (`src/eval/`), clause corpus + tag-driven assembly (`src/clauses/`), contract generation + DOCX/PDF rendering (`src/contracts/`, `src/generator/`, `src/docs/`), RAG search (`src/search/`), a legacy CrewAI drafting crew (`src/crew.py`, entry `main.py`), and finetune data scripts (`scripts/finetune/`).
2. **`fd-coding-law-bench-mcp/`**: FastMCP server exposing 37 tools. It **wraps `src.*` modules in place** — nothing is copied or relocated. It runs in the root project's venv (imports crewai/deepeval/llama-index from there) and reads the root `.env`.
3. **`contract-review-agent/`**: separate LangGraph review service (legal/commercial/completeness triple review) with its **own** `pyproject.toml`/venv and a `frontend/` (npm). Deployed independently.

Key docs: `docs/pipeline-architecture.md`, `docs/tag-driven-assembly.md`, `docs/evaluation-system.md`, `docs/contract-generation-logic.md`. `PRODUCT.md` describes the product; `DESIGN.md` is the UI design system (flat "evidence ledger" style — no shadows/gradients; keep UI text simplified Chinese with zh/en parity).

## Commands

Uses `uv` (Python ≥3.12). From repo root:

```bash
uv sync                                    # install deps
uv run pytest tests                        # run tests
uv run pytest tests/test_store.py -k name  # single test
uv run pytest fd-coding-law-bench-mcp/tests  # MCP tests (hermetic, monkeypatched)
bash scripts/serve_web.sh                  # run the web app on :8010 (uvicorn --reload)
bash scripts/smoke_prod.sh [BASE_URL]      # post-deploy smoke against a live instance (prod by default)
uv pip install -e ./fd-coding-law-bench-mcp  # editable-install MCP package into root venv
python -m fd_coding_law_bench_mcp          # run MCP stdio server (HTTP mode: see its README)
```

`contract-review-agent/` has its own commands (see its README): `uv run uvicorn api.main:app --port 8000` plus `npm run dev` in `frontend/`.

Tests must not hit real LLMs. Most root tests use fakes (`tests/_fakes.py`, `conftest.py`); Postgres-backed tests use a throwaway database.

## Architecture: the evaluation loop

**Clause corpus** (`clauses` table in Postgres, `src/clauses/store.py`): every clause has `tags` (dims like `scenario`, `stance`) and a category — `base` / `tagged` / `custom`. A clause is assembly-ready only when **all** tag dims are `approved` (`src/clauses/tag_review.py`); any dim `rejected` excludes it from assembly (reversible). Tag vocabulary is universal starter dims + per-type dims persisted in `tag_dims` (`src/clauses/tags.py`).

**Contract generation** (`src/clauses/assemble.py`, `src/contracts/`): two paths — the skeleton 母版 template, or tag-driven assembly (base + tagged + custom clauses filtered by `stance`/`scenario`) producing Markdown with `{{slot}}` placeholders. Slots are LLM-filled (temperature 0 for reproducibility) and rendered to Markdown/DOCX/PDF; artifacts stored in RustFS via the S3-compatible client (`src/contracts/artifacts.py`).

**Evaluation** (`src/eval/`): LLM-judge rubric scoring — a rubric's criteria are each scored per draft (`src/eval/scoring.py`, worker pool with 429/503 backoff; a 429 must never become a criterion FAIL). Rubrics sourced `harbor` are read-only; `local` ones are CRUD-able. Compare runs (`src/eval/compare.py`) draft per-prompt and judge against a rubric, producing a criteria × prompts matrix.

**Pipelines** (LangGraph, `docs/pipeline-architecture.md`): `self_heal` (generate → fill → evaluate → improve loop), `auto_reject` (adds a `learn` node that auto-rejects custom clauses hitting the rejection threshold — never touches base/tagged), `tag_iteration_suggest`/`apply` (apply takes a pg_advisory_lock and must run serially; it auto-rolls back if the score drops). The first two are read-only on the `clauses` table and safe to run concurrently.

**MCP server** (`fd-coding-law-bench-mcp/`): tools renamed to concept-first verbs (`contract_generate`, `search_clauses`, …) grouped by tags (`contracts`, `rubrics`, `prompts`, `eval`, `search`, `law`, `tags`, `clauses`, `pipeline`). Harbor rubrics read-only; `search_clauses` degrades to `[]` on backend failure, everything else raises tool errors. Tests monkeypatch the wrapped `src.*` functions — no DB/LLM/network needed.

## OpenSpec workflow

This project uses OpenSpec for change management (`AGENTS.md`). When asked to build/fix/change a feature, use the OpenSpec skills instead of implementing directly: `/opsx:propose` (planning artifacts only — stop after they're done), `/opsx:apply`, `/opsx:update`, `/opsx:explore`, `/opsx:sync`, `/opsx:archive`. Check state first with `openspec list` / `openspec validate --all`. Specs: `openspec/specs/`, active changes `openspec/changes/`, archive `openspec/archive/` (the `fd-coding-law-bench-mcp/` subtree has its own OpenSpec root).

## Operations notes

- Deploys go to the cheap k3s cluster (manifests in `deploy/`); everything public lives under `*.finddatatech.cloud` (`docs/public-api-deploy.md`, runbook `deploy/cheap-box/README.md`). The token118.com domain family and the america box are **retired** (2026-09-09) — the shared Logto IdP is `https://auth.finddatatech.cloud`, object storage is RustFS (S3-compatible; the app still reads `minio_*`/`MINIO_*` env names).
- **Definition of done:** local tests green **and** `scripts/smoke_prod.sh` green against the deployed instance. Local tests run against fakes, so they prove the logic, not the deployment — never call a change shipped on local tests alone. High-risk changes (auth/RBAC, DB schema, PVC/persistence) add a prerequisite stage: satisfy the deploy prerequisites first, then ship in a reversible/degraded mode (e.g. `AUTH_ADMISSION_MODE=warn`) and only then flip to enforcing. Worked example: `deploy/cheap-box/web-rbac-logto.md`.
- Finetuning (`scripts/finetune/`, notes in `微调说明.md` and `docs/finetune-data.md`): SFT data exported to ChatML, LoRA adapters for judge and drafter legs; a known data-lineage caveat exists for the M2 adapters — if judge-adapter quality looks off, suspect training data provenance first.
- Git: remote `origin` points to Gitee (FindDataTehnology/law-bench); GitHub is secondary with Actions disabled.
