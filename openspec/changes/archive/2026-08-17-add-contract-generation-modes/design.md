# Design — Selectable Contract-Generation Modes

## Context

Seven generation capabilities already live in the repo (see `proposal.md` mode
matrix). Two (B/C) are already reachable as JSON APIs under
`/api/contracts/{type}/...`; five (D/E/F/G via MCP tools, plus the G subprocess)
are reachable only from an MCP client or the CLI. The goal is a single UI panel
on the contract detail page where the user picks a mode, fills shared inputs,
and triggers generation — sync modes return immediately with a download link,
async modes return a job id that the panel polls.

The existing async precedent is `POST /api/evaluate` (FastAPI `BackgroundTasks`
+ an `api_eval_runs` table with `pending → running → completed/failed`). This
change reuses that shape, generalized into a `generation_jobs` table so the
panel can poll any async generation run uniformly.

## Goals / Non-Goals

**Goals**
- One detail-page panel, one form, one 「生成」 button; mode chosen by radio.
- Sync modes (A/B/C): respond with download/file URLs in the same request.
- Async modes (D/E/F/G): respond `202 + job_id`, poll `GET /api/generation-jobs/{id}`.
- Uniform job record across async modes so the panel's poller is mode-agnostic.

**Non-Goals**
- New generation logic — every mode calls an existing function/script.
- Auth/permission gating on write modes (UI confirm dialog only this round).
- SSE/WebSocket — polling matches `/api/evaluate`.

## Decisions

### 1. One job table, `kind` discriminator (not one table per mode)

**Choice:** A single `generation_jobs` table with a `kind` column
(`'batch' | 'pipeline' | 'auto_reject' | 'regenerate'`) and a flexible
`result_ref` text column holding a JSON pointer to the mode's real output
(e.g. `{"pipeline_run_id": 42}` for E/F, `{"artifact_ids": [...]}` for C-stored,
`{"files": [...]}` for D/G).

**Rationale:**
- The panel's poller is one shape: `GET job → {status, result_ref}`.
- Mirrors `api_eval_runs` (one table, status machine) rather than fragmenting.
- `pipeline_runs` already stores E/F's rich results — the job row just points at
  it; we don't duplicate E/F into `generation_jobs`.

**Alternatives considered:**
- Reuse `api_eval_runs`: wrong semantics (it's evaluation, not generation).
- Reuse `pipeline_runs` directly: only E/F land there naturally; D/G have no
  home, and the panel would need mode-specific polling endpoints.
- One table per async mode: four pollers, four routes, four schemas.

### 2. Sync vs async split by expected latency

| Mode | Route family | Response | Why |
|------|--------------|----------|-----|
| A | existing download | file stream | <1s, read-only |
| B | existing `POST /generate` | JSON + file URLs | ~1s, read-only |
| C | existing `POST /generate-stored` | JSON + artifact URLs | ~1s, writes DB |
| D | new `POST /generate-batch` | **sync JSON** (seconds, bounded) | parallel but bounded by tag combos |
| E | new `POST /pipeline` | **async 202 + job_id** | minutes, mutates clauses |
| F | new `POST /auto-reject` | **async 202 + job_id** | minutes, mutates clauses |
| G | new `POST /regenerate-template` | **async 202 + job_id** | minutes, rewrites global registry |

D is treated as sync (it's seconds, not minutes, and has no natural job home).
E/F/G are async because they block for minutes and mutate durable state.

### 3. G runs as a subprocess, like `/api/harbor/extract`

**Choice:** Mode G shells out to
`scripts/generate_contract_templates_llm.py` via `subprocess.run` inside the
background task (exactly the pattern in `run_harbor_extraction`).

**Rationale:**
- The script owns global registry mutation (`contracts.json`) + LLM caching to
  `_llm_bodies/`; importing its internals would couple the web layer to those
  file paths. Subprocess keeps the boundary clean.
- Same proven pattern as harbor re-extraction.
- The script writes stdout we can capture into the job's `result_ref`.

**Risk noted:** G rewrites a **committed global file**. The UI confirm dialog
will say so explicitly. A follow-up change can add a dry-run / branch step.

### 4. Shared request shape (`stance` / `scenario` / `custom_clause_ids` / `format`)

**Choice:** One `GenerationRequest` Pydantic model shared by the new routes,
identical fields to the existing `GenerateRequest` plus an optional `mode`
field the panel sends (server validates against the route's mode).

**Rationale:** The panel form already collects these; reusing the shape means
the mode radios all POST the same body, only the route differs.

### 5. Panel wiring: vanilla JS fetch+poll, no new framework

**Choice:** A small `generation-panel.js` under `src/web/static/` that:
- serializes the form,
- POSTs to the route for the selected mode,
- on sync 200: renders download links,
- on 202: stores `job_id`, polls `GET /api/generation-jobs/{id}` every ~3s,
  renders status → on `completed` shows result links, on `failed` shows error.

Matches the existing static-JS style (the dashboard / matrix already use
unbundled JS in `static/`).

## Data flow

```
detail page (contract_detail.html)
   │
   │  user picks mode + fills stance/scenario/format/custom_clause_ids
   ▼
generation-panel.js  ──POST──►  route per mode
   │                               │
   │                  ┌────────────┴───────────────┐
   │                  │                            │
   │           sync (B/C/D)                 async (E/F/G)
   │                  │                            │
   │          200 + file/artifact URLs     202 + job_id
   │                  │                            │ BackgroundTasks
   │                  │                            ▼
   │                  │                  run_*_pipeline / subprocess
   │                  │                            │
   │                  │                            ▼ update job row
   │                  │                            status: completed/failed
   │                  │                            result_ref
   │                  │                            │
   │  ◄──render links──────────────────────────────┘
   │  ◄──poll /api/generation-jobs/{id}────────────┘
```

## Risks / Trade-offs

- **G mutates a committed global file.** Mitigated by a confirm dialog naming
  the file; follow-up can add a git-branch-before step.
- **E/F mutate the clause DB and `pipeline_runs`.** Same exposure the MCP tools
  already have; the web just makes them clickable. Confirm dialog suffices for
  this round; a permission layer is a documented non-goal.
- **Polling cost.** One poller per open detail page, 3s interval, auto-stops on
  terminal status. Negligible vs. the LLM-bound work it waits on.
- **Subprocess failure surface (G).** Capture stderr into the job's
  `error_message`; a non-zero exit → `failed` status, surfaced in the panel.
