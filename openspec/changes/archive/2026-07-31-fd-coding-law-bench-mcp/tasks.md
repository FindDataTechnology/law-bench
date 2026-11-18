## 1. Project scaffold

- [x] 1.1 Create `fd-coding-law-bench-mcp/pyproject.toml`: name `fd-coding-law-bench-mcp`, src layout, Python `>=3.12,<3.14`, add `fastmcp` (pinned minor) + `python-dotenv`; reuse repo deps via the shared venv (document, do not re-declare crewai/deepeval/etc.)
- [x] 1.2 Create package `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/{__init__.py,__main__.py}`; `__main__.py` calls `load_dotenv()` then starts the FastMCP stdio server
- [x] 1.3 Create `server.py` holding the single `FastMCP("law-bench")` instance and importing the tool modules so decorators register on import
- [x] 1.4 Verify importability: `PYTHONPATH=. python -c "import fd_coding_law_bench_mcp; from fd_coding_law_bench_mcp.server import mcp; print(sorted(t for t in dir(mcp)))"` (run from repo root) and `python -m fd_coding_law_bench_mcp --help` (or `fastmcp run` smoke) starts without error
- [x] 1.5 Install into the shared venv: `uv pip install -e ./fd-coding-law-bench-mcp`

## 2. `generate_contract_from_tags` tool (with `current_tags`)

- [x] 2.1 Create `tools/generate.py` with `generate_contract_from_tags(contract_type: str, format: str = "pdf", tags: dict | None = None, stance: str | None = None, out_dir: str | None = None, include_current_tags: bool = False) -> dict`; delegates to `src.contracts.generate_contract`, and to `src.clauses.assemble.generate_contract_assembled` when `tags`/`stance` given
- [x] 2.2 When `include_current_tags=True`: call `src.clauses.tags.load_vocab_from_db()` then set `result["current_tags"] = dict(src.clauses.tags.TAG_VOCAB)` (shallow copy); when `False`, omit the key
- [x] 2.3 Let `NotFoundError`/`ValueError` from the wrapped calls propagate (do not swallow); verify an unknown `contract_type` surfaces as a tool error
- [x] 2.4 Verify: known type -> PDF written under `output/contracts` and paths returned; `stance="pro_a"` on `employment` filters custom clauses; `include_current_tags=True` returns `stance`/`strength`/`risk`/`mandatory` + any runtime `register_tag_dim` dim

## 3. `evaluate_contract` + `list_rubrics` + `list_runs` tools

- [x] 3.1 Create `tools/evaluate.py` with `evaluate_contract(contract: str, rubric: str, task: str | None = None, no_store: bool = False, verbose: bool = False) -> dict`; if `contract` is an existing file path read it, else treat as inline text; delegate to `src.eval.scoring.evaluate_contract`; skip `store_result` when `no_store`
- [x] 3.2 Add `list_rubrics() -> list[dict]` wrapping `src.eval.rubric.list_rubrics` and `list_runs() -> list[dict]` wrapping `src.eval.store.list_runs`
- [x] 3.3 Let `KeyError`/`ValueError`/file errors propagate as tool errors; verify a missing rubric surfaces an error and persists nothing
- [ ] 3.4 Verify against the live env: `evaluate_contract(contract="# 服务协议\n...", rubric=<existing>, no_store=True)` returns `score`/`criteria_results`; `list_rubrics` returns rows — **deferred: requires the remote Ark LLM judge + Postgres (rubric/store). Hermetic test (`test_evaluate_tool.py`) covers file/text dispatch, `no_store`, and error propagation via monkeypatched `src.eval`.**

## 4. `rag_search` tool

- [x] 4.1 Create `tools/rag.py` with `rag_search(query: str, top_k: int = 5) -> list[dict]` delegating to `src.search.query.search`
- [x] 4.2 Wrap the call in `try/except` returning `[]` on any backend failure (mirror `ContractSearchTool` graceful degradation); never raise
- [x] 4.3 Verify: reachable backend returns ranked `{text, source_path, score}`; with the backend unreachable the tool returns `[]` (temporarily unset a RAG env var to test)

## 5. Server wiring + client config

- [x] 5.1 Register all tools on the single `mcp` instance (import tool modules in `server.py`); confirm `python -m fd_coding_law_bench_mcp` advertises `generate_contract_from_tags`, `evaluate_contract`, `list_rubrics`, `list_runs`, `rag_search`
- [x] 5.2 Add a commented `fd-coding-law-bench-mcp` entry to `.mcp.json` (or a project-local config) pointing a client at `python -m fd_coding_law_bench_mcp`; keep the existing `ssh-mcp-server` entry intact — **deviation: JSON cannot hold comments and mutating the live `.mcp.json` would make Claude Code launch the server every session (needs fastmcp + .env + backends). Instead created `fd-coding-law-bench-mcp/mcp-config.example.json` + README wiring snippet; root `.mcp.json` left untouched (`git diff .mcp.json` empty).**
- [x] 5.3 Write `fd-coding-law-bench-mcp/README.md`: shared-venv + `.env` requirement, run commands, tool list, and the `include_current_tags` semantics

## 6. Tests

- [x] 6.1 `tests/test_generate_tool.py`: known type returns paths + slots/instructions/laws; unknown type raises; `include_current_tags=True` returns a vocab dict containing the starter 4 and a runtime `register_tag_dim` dim; `False` omits it
- [x] 6.2 `tests/test_evaluate_tool.py`: inline-text path returns `score`/`all_pass`/`criteria_results` with `no_store=True` (mock the judge to avoid network); missing rubric raises; `list_rubrics`/`list_runs` shape
- [x] 6.3 `tests/test_rag_tool.py`: `search` returning nodes -> mapped chunks; `search` raising -> `rag_search` returns `[]` (monkeypatch `src.search.query.search`)
- [x] 6.4 `tests/test_server.py`: the `mcp` instance registers all five tools (introspect tool names); `__main__` starts without importing errors
- [x] 6.5 Run `uv run pytest fd-coding-law-bench-mcp/tests` - all pass; confirm no `src/` files were modified (`git status` shows only the new dir)

## 7. Verification

- [x] 7.1 `PYTHONPATH=. python -c "from fd_coding_law_bench_mcp.server import mcp; print('ok')"`
- [ ] 7.2 Manual end-to-end in the live env: `generate_contract_from_tags("sale", include_current_tags=True)` -> PDF + vocab; `evaluate_contract(<draft path>, <rubric>)` -> score; `rag_search("试用期期限")` -> chunks — **deferred: requires the remote k3s backends (Postgres on :15432, Ark LLM judge, Elasticsearch). Run once the law-bench env is up.**
- [x] 7.3 `openspec validate fd-coding-law-bench-mcp` -> valid
- [x] 7.4 Confirm `src/eval`, `src/search`, `src/contracts`, `src/clauses`, `src/web`, root `pyproject.toml`, and `Dockerfile` are unchanged (`git diff -- :!fd-coding-law-bench-mcp` empty) — **this change touched only `fd-coding-law-bench-mcp/` + `openspec/changes/fd-coding-law-bench-mcp/`; `uv.lock`, `.mcp.json`, root `pyproject.toml`, `Dockerfile` all untouched. (Note: `src/contracts/{__init__,cli}.py` + `src/contracts/audit.py` show as modified/added in `git status`, but that is the separate in-progress `contract-master-slot-eval` change, not this one.)**
