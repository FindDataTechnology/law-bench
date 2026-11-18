## Why

law-bench's three core capabilities - tag/stance-filtered contract generation (`src/contracts` + `src/clauses`), rubric contract evaluation (`src/eval`), and clause RAG search (`src/search`) - are reachable today only through CLI entry points (`python -m src.contracts`, `python -m src.eval.run`) and the FastAPI web app. An LLM coding agent (e.g. fd-coding) operating on law-bench has no structured programmatic surface: it must shell out to CLIs or drive the web UI, and it cannot discover the *current* custom-tag vocabulary (which may include dimensions registered in-memory but not yet persisted to `tag_dims`) before generating. A single MCP server wrapping these capabilities gives the agent typed, tool-callable access and a way to read the live tag vocabulary in one round-trip.

## What Changes

- **New FastMCP server project** `fd-coding-law-bench-mcp/` at the repo root: its own `pyproject.toml`, a `python -m fd_coding_law_bench_mcp` entry point, and a `fastmcp run` launcher. It imports `src.*` via the repo-root pythonpath (shared venv) - no relocation of existing code.
- **Tool `generate_contract_from_tags`**: wraps `src.contracts.generate_contract` and `src.clauses.assemble.generate_contract_assembled`. Parameters: `contract_type`, optional `tags` (dict) / `stance`, `format` (`docx`/`pdf`/`both`), `out_dir`, and `include_current_tags: bool`. When `include_current_tags=True` the result carries `current_tags` = the live `TAG_VOCAB` (starter 4 + DB `tag_dims` + any dims registered at runtime via `register_tag_dim`) - the "current temporary custom tags" - so the caller can see what tag values are available before/while generating.
- **Tool `evaluate_contract`**: wraps `src.eval.scoring.evaluate_contract`. Parameters: `contract` (path or text), `rubric` name, optional `task` description, `no_store` flag. Returns the rubric score, per-criterion pass/fail, and judge model; persisted to the eval DB unless `no_store`. Companion `list_rubrics` and `list_runs` tools wrap the same-named `src.eval` helpers.
- **Tool `rag_search`**: wraps `src.search.query.search(query, top_k)`. Returns ranked chunks (text, source_path, score); degrades to `[]` on backend failure (mirrors the existing `ContractSearchTool` graceful-degradation contract).
- **Wrap-in-place, no relocation**: `src/eval` and `src/search` stay where they are; the MCP imports them. No existing requirement is altered - the MCP is a new consumer/interface over unchanged modules.
- **Optional `.mcp.json` registration**: a documented (commented) entry wiring the server into a client like Claude Code, alongside the existing `ssh-mcp-server`.

## Capabilities

### New Capabilities
- `law-bench-mcp`: a FastMCP server exposing law-bench's tag/stance-filtered contract generation (with live custom-tag discovery), contract rubric evaluation, and clause RAG search as MCP tools, wrapping existing `src` modules in place.

### Modified Capabilities
<!-- None. The MCP is a new interface over unchanged modules; rag-search and evaluation-rules requirements are consumed as-is. -->

## Impact

- **New code**: `fd-coding-law-bench-mcp/` - `pyproject.toml`, `src/fd_coding_law_bench_mcp/{__init__,__main__,server}.py`, `tools/{generate,evaluate,rag,tags}.py`, `README.md`; tests under `fd-coding-law-bench-mcp/tests/`.
- **Dependencies**: adds `fastmcp` (and its transitive `mcp`) to the new project's `pyproject.toml`; reuses the repo's existing deps (crewai, deepeval, llama-index, psycopg, python-docx) - no changes to the root `pyproject.toml`.
- **No changes** to `src/eval`, `src/search`, `src/contracts`, `src/clauses`, `src/web`, their tests, or the root `pyproject.toml`/`Dockerfile`.
- **Operations**: run via `python -m fd_coding_law_bench_mcp` or `fastmcp run fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/server.py`; wire into a client through `.mcp.json`.
- **Out of scope**: physically relocating `src/eval`/`src/search` into the MCP (wrap-in-place v1; follow-up change if desired); exposing clause CRUD/admin or the web app over MCP; auth/multi-tenant; a streaming transport.
