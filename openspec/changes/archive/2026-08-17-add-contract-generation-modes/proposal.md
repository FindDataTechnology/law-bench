# Add Selectable Contract-Generation Modes to the Web

## Why

The repo already owns **seven** distinct contract-generation capabilities, but only the
simplest one (skeleton 母版 download) is reachable from a web button. The rest exist only
as MCP tools (`contract_generate`, `contract_generate_batch`, `contract_generate_stored`,
`self_heal_pipeline_run`, `auto_reject_pipeline_run`) or as a CLI script
(`scripts/generate_contract_templates_llm.py`). The user has batch-generated contract
templates before via these tools and wants them surfaced in the web UI as a single
selectable panel on the contract detail page — "都加上吧，页面选择就好".

The JSON APIs for modes B (assemble) and C (store-to-MinIO) **already exist**
(`POST /api/contracts/{type}/generate`, `POST /api/contracts/{type}/generate-stored`).
The work is therefore mostly (1) a UI panel + form, (2) thin web routes for the
MCP-only modes D/E/F/G, and (3) a uniform async-job table so minute-long runs (E/F/G)
can be polled in-place instead of blocking the request.

## What Changes

- **Contract detail page** gains a 「生成合同模板」 panel: a mode radio group
  (A–G), shared `stance` / `scenario` / `format` / `custom_clause_ids` inputs, and a
  「生成」 button. Result area shows download links (sync modes) or a job-status card
  (async modes).
- **New web routes** under `/api/contracts/{type}/...` that wrap the MCP-only logic:
  - `POST /api/contracts/{type}/generate-batch` → mode D (parallel across tag combos)
  - `POST /api/contracts/{type}/pipeline` → mode E (`run_self_heal_pipeline`)
  - `POST /api/contracts/{type}/auto-reject` → mode F (`run_auto_reject_pipeline`)
  - `POST /api/contracts/{type}/regenerate-template` → mode G (LLM mother-template
    regeneration subprocess)
- **New `generation_jobs` table** + CRUD in `src/eval/store.py`: a uniform
  `pending → running → completed/failed` job record for async modes (D/E/F/G), with a
  `kind` discriminator and a `result_ref` pointer (e.g. `pipeline_run_id` for E/F,
  artifact ids / body for D/G). Mirrors the proven `api_eval_runs` shape.
- **Polling endpoints** `GET /api/generation-jobs` (list) and
  `GET /api/generation-jobs/{id}` (detail), reusing the same background-task pattern as
  `/api/evaluate`.
- Modes A (skeleton download) is **already wired** (the existing download buttons); the
  panel simply re-states it as the "fast / read-only" option.

## Capabilities

### New Capabilities
- `contract-generation-jobs`: async job table + REST polling for long-running
  generation runs (D/E/F/G).

### Modified Capabilities
- `contract-templates-web`: the detail page gains the generation-mode panel and the
  quick (B/C) and async (D/E/F/G) trigger routes.

## Impact

- **New files:**
  - `src/web/routes/generation.py` — new router (D/E/F/G + job polling)
  - `src/web/templates/contract_detail.html` — extend with the generation panel (or a
    partial included from it)
  - `src/web/static/` generation-panel JS (fetch + poll + render)
- **Modified files:**
  - `src/eval/store.py` — add `generation_jobs` DDL + CRUD helpers
  - `src/web/models.py` — add job request/response Pydantic models
  - `src/web/app.py` — include the new router
  - `src/web/templates/contract_detail.html` — inject the panel markup
- **No changes to:** `src/contracts/`, `src/clauses/`, the MCP server, or the pipeline
  graphs themselves — the web layer only *calls* the existing functions
  (`generate_contract_assembled`, `run_self_heal_pipeline`,
  `run_auto_reject_pipeline`, the `generate_contract_templates_llm.py` subprocess).

## Mode → wiring matrix

| Mode | What it does | Web status | Async? | Writes |
|------|--------------|-----------|--------|--------|
| A 母版骨架 | render registered 母版 template | **already wired** (download buttons) | no | none |
| B 标签组装 | custom>tagged>base assembly + coherence gate | **API exists** `POST /generate` | no | output file |
| C 存储 MinIO | B + upload + `contract_artifacts` row | **API exists** `POST /generate-stored` | no | DB + MinIO |
| D 批量组装 | parallel across tag combos (`contract_generate_batch`) | **new route** | short | output files |
| E 自愈流水线 | generate→fill→evaluate→improve loop | **new route** | minutes | clauses + `pipeline_runs` |
| F 自动拒绝 | E + `learn` node, auto-reject recurring custom clauses | **new route** | minutes | clauses + `pipeline_runs` |
| G LLM 重生成 | re-draft 母版 body via DRAFTER LLM (subprocess) | **new route** | minutes | **global `contracts.json`** |

## Non-Goals

- No new generation *logic* — every mode calls an existing function/script; we only add
  the web surface + job bookkeeping.
- No SSE/WebSocket — polling is sufficient and matches `/api/evaluate`.
- No auth/permission gate on the write modes (E/F/G mutate DB/global files) in this
  change; a confirm-dialog in the UI is the only guard. (A permission layer can follow.)
- No auto-cleanup of old `generation_jobs` rows in this change.
