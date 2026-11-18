## Context

The law-bench MCP server (`fd-coding-law-bench-mcp/`) advertises 27 tools
registered with bare `@mcp.tool` decorators - no `name=`, no `tags=`. The MCP
tool name is derived from the Python function name, so clients see a flat,
inconsistently-named list (e.g. `generate_contract_from_tags`, `list_rubrics`,
`get_compare_matrix`, `rag_search`). There is no grouping exposed to clients,
and the "tags" concept the server already deals in (`include_current_tags`,
the `tags=` param) has no dedicated tool surface.

Tool modules live in `fd_coding_law_bench_mcp/tools/` (`generate`, `evaluate`,
`rubrics`, `prompts`, `compare`, `law_info`, `rag`). Each `@mcp.tool` function
wraps `src.*` in place at call time. The server is launched via
`python -m fd_coding_law_bench_mcp`.

The rename blast radius is contained inside the package: 5 test files in
`fd-coding-law-bench-mcp/tests/` and `README.md`. `.mcp.json` /
`mcp-config.example.json` configure only the server command, not tool names, so
no external client wiring breaks beyond the tool-name strings callers invoke.

## Goals / Non-Goals

**Goals:**
- Rename all 27 tools to concept-first verb names so they self-organize by
  concept in any MCP client's tool picker.
- Establish 7 concept groups via FastMCP `tags=`: `contracts`, `rubrics`,
  `prompts`, `eval`, `search`, `law`, `tags`.
- Make the `tags` group non-empty by adding 2 read-only tag tools wrapping
  `src.clauses.tags`.
- Update tests + README to the new names.

**Non-Goals:**
- No writable tag-dim management. `register_tag_dim` is in-memory only and
  there is no persisted tag-dim CRUD in `src`; exposing writes is a separate
  change (build src CRUD first).
- No `src.*` modifications - tools wrap `src` in place; `src.clauses.tags` is
  only read.
- No changes to tool *behavior*, parameters, or return shapes - only names,
  the `tags=` kwarg, and the 2 new read-only tools.
- No backward-compatibility aliases (old names will not resolve). Callers must
  migrate.

## Decisions

### Decision 1: Concept-first verb names, underscore separator
**Choice:** `<concept>_<verb>` / `<entity>_<verb>`, underscore-separated.
e.g. `generate_contract_from_tags` -> `contract_generate`, `rag_search` ->
`search_clauses`, `list_law_info_types` -> `law_types`, `get_compare_matrix` ->
`compare_matrix`, `get_run_detail` -> `run_get`.

**Why:** Concept-first sorts all tools of a concept together alphabetically in
every client (the MCP protocol has no formal group field, so names are the
universal grouping lever). Verb voice (`_generate`, `_list`, `_create`) matches
the action and is consistent with the existing `list_*` / `get_*` style.
Underscore is universally safe across clients; `.` / `:` separators are
spec-quirky and rendered inconsistently.

**Alternatives considered:**
- Action-first (`generate_contract`) - sorts by verb, fragments concepts.
- Noun voice (`contract_generation`) - rejected per user decision (verb voice).
- `.`/`:` namespace separators - rejected; client-dependent rendering.

### Decision 2: 7 concept groups via FastMCP `tags=`
**Choice:** Add `tags={"<concept>"}` to every tool. Groups: `contracts`,
`rubrics`, `prompts`, `eval`, `search`, `law`, `tags`. Within a group,
multiple name prefixes are allowed (`rubric_*` + `criterion_*` both `rubrics`;
`compare_*` + `run_*` both `eval`; `search_*` alone in `search`; `law_*` in
`law`).

**Why:** Name prefixes alone yield ~9 micro-groups by prefix; the user asked
for *concept* groups. `tags=` is FastMCP's literal group primitive and makes
the 7-concept grouping machine-readable (a tag-aware client or `get_tools()`
filter sees the concept). Names handle client-side sorting; tags encode the
concept. Cost is one kwarg per tool.

**Alternatives considered:**
- Names only, no `tags=` - rejected per user delegation; tags= makes "groups"
  real to the framework, not just an alphabetical artifact.
- One group per prefix (9 groups) - too granular; fragments rubric/criterion
  and compare/run which are single workflows.

### Decision 3: `tags` group is read-only (2 new tools)
**Choice:** Add `tag_vocab_list` (wraps `tag_vocab_for_type`) and `tag_validate`
(wraps `validate_tags`). Both read-only.

**Why:** `register_tag_dim` is in-memory only - exposing it would let a client
register a dim invisible to the web app and lost on restart (footgun). There is
no persisted tag-dim write path in `src` (only `seed_manifest.py` INSERTs). So
a writable tags group requires building src CRUD first - out of scope for a
rename. The 2 read-only tools make the group honest and non-empty without
scope creep.

**Alternatives considered:**
- Expose `register_tag_dim` as `tag_dim_register` with an ephemeral caveat -
  rejected; footgun even when documented.
- Drop the `tags` group entirely - rejected per user decision ("tag is a
  group").
- Build persisted tag CRUD now - rejected; scope creep beyond a rename.

### Decision 4: Full rename map

| Concept (tag) | Old name | New name |
|---|---|---|
| contracts | generate_contract_from_tags | contract_generate |
| contracts | evaluate_contract | contract_evaluate |
| rubrics | list_rubrics | rubric_list |
| rubrics | get_rubric | rubric_get |
| rubrics | create_rubric | rubric_create |
| rubrics | update_rubric | rubric_update |
| rubrics | delete_rubric | rubric_delete |
| rubrics | add_criterion | criterion_add |
| rubrics | update_criterion | criterion_update |
| rubrics | delete_criterion | criterion_delete |
| rubrics | reorder_criteria | criterion_reorder |
| prompts | list_prompts | prompt_list |
| prompts | get_prompt | prompt_get |
| prompts | create_prompt | prompt_create |
| prompts | update_prompt | prompt_update |
| prompts | delete_prompt | prompt_delete |
| eval | run_compare | compare_run |
| eval | list_compares | compare_list |
| eval | get_compare | compare_get |
| eval | get_compare_matrix | compare_matrix |
| eval | list_runs | run_list |
| eval | get_run_detail | run_get |
| eval | get_run_draft | run_draft |
| search | rag_search | search_clauses |
| law | list_law_info_types | law_types |
| law | get_law_info | law_info |
| law | extract_legal_references | law_references |
| **tags (new)** | - | tag_vocab_list |
| **tags (new)** | - | tag_validate |

The 2 new tag tools go in a new `tools/tags.py` module (mirroring the
one-module-per-concept layout) or alongside `generate.py`; new module preferred
for consistency.

## Risks / Trade-offs

- **[Breaking change for old tool names]** -> No aliases provided. Mitigation:
  blast radius is contained (5 test files + README inside the package); no
  external client wiring references tool names. Tests are updated in the same
  change. Document the rename prominently in README.
- **[In-flight OpenSpec changes]** `mcp-eval-tools` (25/26) and
  `replace-region-with-scenario` (23/28) touch the same tool surface.
  -> User confirms both are already landed; rename proceeds on current main.
  Verify the 27-tool inventory is current before renaming (re-grep `@mcp.tool`
  at implementation start).
- **[Dual prefix within a group]** `rubric_*` + `criterion_*` share the
  `rubrics` tag; `compare_*` + `run_*` share `eval`. -> Intentional; the tag
  encodes the concept, the prefix encodes the entity. Documented in the
  Concept Grouping spec requirement.
- **[`tags={"tags"}` self-reference]** The tags-concept group's FastMCP tag
  value is the string `tags`. -> Mildly awkward but accurate; no functional
  issue. Acceptable.
- **[Unspecced tools renamed without spec deltas]** ~22 tools (rubric/criterion
  CRUD, prompts, compare, law_info) have no existing spec requirements.
  -> No spec delta needed for them; the Concept Grouping requirement references
  their new names so the grouping is still contracted.

## Migration Plan

1. Rename each `@mcp.tool` function in `tools/*.py` per the map; add
   `tags={"<concept>"}` kwarg to each decorator.
2. Add `tools/tags.py` with `tag_vocab_list` and `tag_validate` (tagged
   `tags`), wrapping `src.clauses.tags`.
3. Update `tests/test_{rag,tools_registration,server,generate,evaluate}_tool.py`
   to the new names (including any registration-count assertions in
   `test_tools_registration.py` / `test_server.py` - counts grow by 2).
4. Update `README.md` tool table to new names + add a concept-group column.
5. Verify: `uv run pytest fd-coding-law-bench-mcp/tests` green; launch the
   server and confirm `tools/list` shows 29 tools grouped by the 7 tags.

**Rollback:** Revert the commit; no data migration is involved (no DB schema,
no persisted state changes). Old tool names return on revert.

## Open Questions

None remaining - separator (underscore), voice (verb), tags= (yes), tags group
(read-only), and timing (land now) are all decided.
