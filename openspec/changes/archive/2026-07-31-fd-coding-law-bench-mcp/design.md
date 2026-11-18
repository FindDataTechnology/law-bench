## Context

law-bench (repo: `chinese-contract-drafter`) ships three capabilities that today are reachable only via CLI and a FastAPI web app:

- **Contract generation** - `src/contracts/generator.py::generate_contract` (DOCX/PDF from a `{{slot}}` template) and `src/clauses/assemble.py::generate_contract_assembled` (assembles base + tagged + custom clauses, with an optional `stance` filter over `tags`).
- **Contract evaluation** - `src/eval/scoring.py::evaluate_contract` (deepeval GEval LLM-judge, one pass/fail per criterion, all-pass scoring), with `src/eval/rubric.py::list_rubrics` and `src/eval/store.py::list_runs` / `store_result`.
- **RAG search** - `src/search/query.py::search(query, top_k)` over the Elasticsearch vector store, already wrapped by the graceful-degrading `ContractSearchTool`.

The custom-tag vocabulary lives in `src/clauses/tags.py`: `TAG_VOCAB` (starter 4: `stance`/`strength`/`risk`/`mandatory`) merged at runtime with the `tag_dims` table via `load_vocab_from_db()`, plus any dimension added in-process via `register_tag_dim()` (temporary, not yet persisted). An LLM coding agent (fd-coding) needs a single structured surface to call these and to read that live vocabulary.

Two coupling facts drove the design (confirmed by grepping the repo):

- `src/eval` is imported by **~58 sites** - not just evaluation, but the shared Postgres layer (`store.py`, `db.py`, `errors.py::NotFoundError`, `manage.py`, the CRUDs) used by `src/clauses`, `src/contracts`, `src/web`, scripts, and ~20 test files. It is shared infrastructure, not a movable leaf.
- `src/search` is imported by only **3 sites** (`src/crew.py`, `src/web/routes/search.py`, `tests/test_search.py`) - a movable leaf, but moving it buys nothing if the goal is agent access.

Per the user's decision, this change **wraps in place** (no relocation) and lives in a **top-level project dir** (`fd-coding-law-bench-mcp/`) with its own `pyproject.toml`, sharing the repo venv so it can `import src.*` via the repo-root pythonpath.

## Goals / Non-Goals

**Goals:**
- A FastMCP server an LLM agent can call to generate tag/stance-filtered contracts, evaluate a draft against a rubric, and RAG-search the clause corpus.
- Let the agent discover the **current** custom-tag vocabulary (including temporary in-memory dims) in the same call it uses to generate.
- Zero changes to `src/eval`, `src/search`, `src/contracts`, `src/clauses`, `src/web`, their tests, or the root `pyproject.toml`/`Dockerfile`.
- Honest error propagation: wrapped-module failures reach the agent as tool errors (except `rag_search`, which degrades to `[]` per its existing contract).

**Non-Goals:**
- Physically relocating `src/eval` or `src/search` into the MCP (wrap-in-place v1; a follow-up change can relocate if ownership consolidation is wanted).
- Exposing clause CRUD/admin, the contract-slot audit, the web app, or law-info over MCP.
- Auth, multi-tenancy, or a remote (HTTP/SSE) transport - stdio only for v1.
- Caching, retries, or rate-limiting inside the MCP.

## Decisions

### D1: FastMCP + stdio transport
**Choice**: Build the server with the `fastmcp` package, stdio transport, runnable via `python -m fd_coding_law_bench_mcp` and `fastmcp run`.
**Rationale**: FastMCP gives decorator-based tool registration (`@mcp.tool`) with automatic schema generation from type hints - the fastest path to a typed agent surface, matching the "fast mcp project" ask. Stdio is the default MCP transport and is what local clients (Claude Code) expect.
**Alternatives**: Raw `mcp` Python SDK (more boilerplate, manual schema); TypeScript MCP SDK (cannot `import src.*` directly - would require an HTTP shim over the existing web app).

### D2: Wrap-in-place, no relocation
**Choice**: The MCP imports `src.eval`, `src.search`, `src.contracts`, `src.clauses` from their current paths. No code is moved.
**Rationale**: `src/eval` is shared infra for ~58 sites; relocating it (or even its engine half) risks breaking clauses/web/contracts/scripts for zero behavior change - the MCP only needs to *call* these, not own them. Wrapping gives the agent a clean interface while leaving ownership and test surface untouched.
**Alternatives**: Relocate eval engine + `src/search`, keep shared store (medium risk, partial ownership move); full physical move with shims (high risk, ~60 import edits). Both rejected for v1 - the user selected wrap-in-place.

### D3: Top-level project dir with its own pyproject, shared venv
**Choice**: `fd-coding-law-bench-mcp/` at the repo root, src-layout package `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/`, its own `pyproject.toml` adding only `fastmcp` (reusing the repo's existing deps). It imports `src.*` because the shared venv + repo-root pythonpath already expose them (root `pyproject.toml` sets `pythonpath = ["."]`).
**Rationale**: Distinct project identity and dependency isolation (`fastmcp`/`mcp` do not pollute the root `pyproject.toml` or the deployed law-bench image), while avoiding the vendoring/install step a separate repo would need to reach `src.*`.
**Alternatives**: `src/law_bench_mcp/` inside the root package (simplest imports, but no separate identity and forces `fastmcp` into the root deps / Docker image); separate git repo (cleanest separation, but must vendor or pip-install `src.*` - not worth it for a wrapper).

### D4: `current_tags` = live `TAG_VOCAB` snapshot after `load_vocab_from_db`
**Choice**: When `include_current_tags=True`, the generate tool calls `load_vocab_from_db()` (merges `tag_dims` into `TAG_VOCAB`) and returns `dict(TAG_VOCAB)` (a shallow copy so the caller cannot mutate the process vocab). This captures starter + DB + any in-process `register_tag_dim` additions - i.e. the "current temporary custom tags".
**Rationale**: Reading the table directly would miss temporary dims registered in-memory but not persisted (the whole point of "temporary custom tags"). Snapshotting `TAG_VOCAB` after `load_vocab_from_db` is the only read that reflects all three sources at call time. Shallow copy prevents the agent from corrupting the server's vocab.
**Alternatives**: Return `load_vocab_from_db()`'s return value directly (it returns the live dict - caller mutation risk); skip `load_vocab_from_db` (misses DB-only dims).

### D5: `rag_search` degrades to `[]`; everything else propagates
**Choice**: `rag_search` wraps `search()` in `try/except` and returns `[]` on any error (mirroring `ContractSearchTool._run`). All other tools let exceptions propagate; FastMCP surfaces them to the client as tool errors.
**Rationale**: RAG is optional retrieval that must never block generation (existing contract). Evaluation/generation failures are actionable - the agent should see them, not an empty result that looks like success.
**Alternatives**: Catch-all returning `{error: ...}` objects (hides failures behind a success status; agent may mis-handle); propagate `rag_search` errors too (breaks the never-blocks contract).

### D6: `evaluate_contract` accepts path OR inline text
**Choice**: The `contract` parameter is a string; if it is an existing file path the tool reads it, otherwise it is treated as inline contract text. `no_store=True` skips DB persistence.
**Rationale**: An agent may have a path (a generated DOCX/PDF companion, a draft file) or just-produced text; one param covers both without a separate tool. Mirrors the flexibility of `src.eval.run`'s `--contract` while adding text support.
**Alternatives**: Separate `contract_path` / `contract_text` params (ambiguous when both given); two tools (needless).

### D7: Tool set and granularity
**Choice**: Five tools - `generate_contract_from_tags`, `evaluate_contract`, `list_rubrics`, `list_runs`, `rag_search`. Each maps 1:1 to an existing `src` function; `list_rubrics`/`list_runs` are cheap companions that let the agent pick a rubric or review history without an extra round-trip to the CLI.
**Rationale**: One tool per capability keeps schemas small and lets the agent reason about each independently. The `list_*` helpers exist as CLIs already (`--list-rubrics`, `--list-runs`) and are trivial wraps.
**Alternatives**: A single `law_bench` tool with an `action` enum (large schema, worse agent UX); omit `list_*` (agent must guess rubric names).

## Risks / Trade-offs

- **[Shared venv coupling]** The MCP imports `src.*`, so it must run in an environment where the repo's deps (crewai, deepeval, llama-index, psycopg, python-docx) are installed and `.env` is loaded (it needs `database_url`, RAG vars, Ark/OpenRouter keys). -> Mitigation: the server calls `load_dotenv()` at startup; document the shared-venv requirement in the project README. Acceptable since it runs alongside law-bench, not as a standalone artifact.
- **[TAG_VOCAB is process-global]** `register_tag_dim` mutates module-global state, so `current_tags` reflects only dims registered in *this* server process. A dim registered in the web app's process is invisible to the MCP until persisted to `tag_dims`. -> Mitigation: documented as expected behavior; `load_vocab_from_db()` still surfaces all persisted dims. The "temporary" dims are by definition in-process.
- **[Eval is LLM+network dependent]** `evaluate_contract` calls the deepeval GEval judge over the Ark endpoint; a slow/unreachable judge makes the tool slow/fail. -> Mitigation: errors propagate honestly to the agent (D5); `no_store` keeps the call side-effect-free for retries.
- **[Wrap-in-place means dual surfaces]** The CLI and web app remain; the MCP is a third surface over the same code. Behavior drift is low (same functions) but the agent must be told the MCP exists. -> Mitigation: README + `.mcp.json` example; out of scope to deprecate CLIs.
- **[fastmcp version churn]** FastMCP is evolving; a breaking release could break the server. -> Mitigation: pin `fastmcp` to a known-good minor in the project `pyproject.toml`.

## Migration Plan

1. Add `fd-coding-law-bench-mcp/` (pyproject, package, tools, tests) - no `src/` edits.
2. Install the project into the shared venv: `uv pip install -e ./fd-coding-law-bench-mcp` (or run via `PYTHONPATH=.`).
3. Add a commented `.mcp.json` entry (or project-local `mcp_servers` config) pointing a client at `python -m fd_coding_law_bench_mcp`.
4. Smoke-test each tool against the live law-bench env (known `contract_type`, an existing rubric, a RAG query).
- **Rollback**: delete `fd-coding-law-bench-mcp/` and the `.mcp.json` entry. No `src/` changes to revert; law-bench is unaffected.

## Open Questions

- Should a later change expose clause CRUD / admin over MCP (so the agent can curate tags, not just read them)? Deferred - v1 is read/generate/evaluate/search only.
- Should we add an HTTP/SSE transport for non-stdio clients? Deferred - stdio covers the local-agent case.
- Is a separate venv (isolating `fastmcp`/`mcp` from law-bench's deps) ever needed? Not for v1 - the shared venv is simpler and the deps do not conflict.
