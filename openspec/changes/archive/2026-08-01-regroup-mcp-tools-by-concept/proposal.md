## Why

The law-bench MCP server advertises 27 tools registered with bare `@mcp.tool`
(no `name=`, no `tags=`), so clients see a flat, inconsistently-named list
(`list_rubrics` vs `get_compare_matrix` vs `generate_contract_from_tags` vs
`rag_search`). There is no grouping exposed, and the "tags" concept the server
already deals in has no dedicated tool surface. Renaming to concept-first verb
names and adding FastMCP `tags=` regroups the surface by concept (contracts,
rubrics, prompts, eval, search, law, tags) so it is self-organizing and
scannable in any MCP client's tool picker.

## What Changes

- **BREAKING** — Rename all 27 existing tools to concept-first verb names
  (e.g. `generate_contract_from_tags` → `contract_generate`,
  `evaluate_contract` → `contract_evaluate`, `rag_search` → `search_clauses`,
  `list_law_info_types` → `law_types`, `get_compare_matrix` → `compare_matrix`,
  `get_run_detail` → `run_get`). The MCP tool name is derived from the Python
  function name, so each `@mcp.tool` function is renamed.
- Add a FastMCP `tags={"<concept>"}` kwarg to every tool, establishing 7
  concept groups: `contracts`, `rubrics`, `prompts`, `eval`, `search`, `law`,
  `tags`. Within a concept, multiple name prefixes may exist (e.g. `rubric_*`
  and `criterion_*` both tagged `rubrics`; `compare_*` and `run_*` both tagged
  `eval`).
- Add 2 new **read-only** tag tools under the `tags` group, wrapping
  `src.clauses.tags`: `tag_vocab_list` (wraps `tag_vocab_for_type`) and
  `tag_validate` (wraps `validate_tags`). These make the `tags` group
  non-empty. Writable tag-dim management is explicitly out of scope (no
  persisted tag-dim CRUD exists in `src` today; that is a separate change).
- Update the 5 test files in `fd-coding-law-bench-mcp/tests/` and the
  `README.md` tool table to the new names.

## Capabilities

### New Capabilities
<!-- None: the new tag tools extend the existing law-bench-mcp surface rather
than introducing a separately-specced capability. -->

### Modified Capabilities
- `law-bench-mcp`: tool names change to concept-first verb form; FastMCP
  `tags=` concept grouping is added to every tool; 2 new read-only tag tools
  (`tag_vocab_list`, `tag_validate`) are added to the advertised surface.

## Impact

- **Code**: `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/*.py`
  (rename `@mcp.tool` functions + add `tags=` kwarg); one new tool module or
  additions to an existing module for the 2 tag tools.
- **Tests**: `fd-coding-law-bench-mcp/tests/` — 5 files
  (`test_{rag,tools_registration,server,generate,evaluate}_tool.py`) reference
  the old tool names and must be updated.
- **Docs**: `fd-coding-law-bench-mcp/README.md` tool table.
- **No `src.*` changes** — tools wrap `src` in place; `src.clauses.tags` is
  only read, not modified.
- **No `.mcp.json` / `mcp-config.example.json` changes** — only the server
  command is configured there, not tool names, so external client wiring is
  unaffected beyond the tool-name strings callers invoke.
- **Breaking for any caller** using the old tool-name strings; blast radius is
  contained inside the `fd-coding-law-bench-mcp` package (tests + README).
