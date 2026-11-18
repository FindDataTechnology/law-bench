## Why

The repo already has every ingredient an agent needs to draft a Chinese contract: 43 contract-class templates with `{{slot}}` placeholders and per-slot instruction manifests (`src/contracts/`), per-type 法律法规 surveys from Doubao+DeepSeek (`src/eval/law_info` + `src/contracts/legal.extract_laws_for_type`), a tag-driven clause-assembly model (`src/clauses/assemble.generate_contract_assembled`, override `custom > tagged > base` + coherence gate), a controlled tag vocabulary per type (`src/clauses/tags`), and a slot ontology covering ~270 canonical slot concepts with role-prefixed aliases (`src/contracts/slot_ontology`). All of this is reachable today over **MCP** (`fd-coding-law-bench-mcp/`) and over **HTML** (`/contracts/{type}` renders template + slots + laws), but the **JSON HTTP API** under `/api` only covers the eval side - rubrics, prompts, compare, harbor, search. There is **no** `/api` endpoint for slots, laws, tags, clauses, or contract generation.

So an agent that speaks plain HTTP - `curl`, `fetch`, an SDK, a non-MCP framework - cannot gather the context to draft a contract, nor ask the system to assemble one. This change exposes the contract-generation context (and assembly) as a documented JSON API under `/api/docs`, so other people can build agents on top of it: one comprehensive bundle call gives an agent the template skeleton, slot instructions, the laws that apply, the tag dimensions that specialize the contract, the canonical section order, and pointers to the rubric/prompts - everything it needs to generate a contract in its own LLM, with an optional `generate` endpoint for agents that want tag-pick-and-go.

## What Changes

- **New JSON API capability** under `src/web/routes/` - a `contract-context` router included in `src/web/app.py` alongside the existing `api` router, all endpoints **documented in `/api/docs`** (no `include_in_schema=False`):
  - `GET /api/contracts` - list supported contract classes `[{key, zh}]`.
  - `GET /api/contracts/{type}` - **the comprehensive bundle** for one type: template (body + slots), slot instructions, structured 法律法规 refs, the tag vocabulary, canonical section order, a clause-availability summary, and pointers to the per-type rubric + prompts.
  - `GET /api/contracts/{type}/slots` - **the slot API**: the slot-instruction manifest for the type, enriched with the slot ontology so variant slot names (`seller_address` -> `address`) are covered; each entry carries a `source`.
  - `GET /api/contracts/{type}/laws` - structured law refs **plus** the full Doubao+DeepSeek survey markdown.
  - `GET /api/contracts/{type}/tags` - the merged tag vocabulary `{dim: [values]}` for the type.
  - `GET /api/contracts/{type}/clauses` - the clause catalog, filterable (`?scenario=&stance=&source=`) and paginated (`?limit=&offset=`), returning clause bodies on demand.
  - `POST /api/contracts/{type}/generate` - assemble + render via the existing `generate_contract_assembled`, **defaulting to `docx`** (matching the service default); `pdf`/`both` also return download URLs, `markdown` returns text only. The response always carries `body_text`. Coherence-gate failure -> 422 with a diagnostic.
- **No new business logic.** Every endpoint is a thin route over an existing service function (`get_template`, `get_slot_instructions`, `extract_laws_for_type`, `get_law_info`, `tag_vocab_list`, `list_clauses`, `generate_contract_assembled`, `slot_ontology.instruction_for_slot`); the web layer already has a `Depends(get_db)` pattern for DB-backed reads.
- **No changes** to `src/contracts/`, `src/clauses/`, the assembly model, the coherence gate, the MCP server, or the existing HTML `/contracts` pages (the JSON routes are a parallel surface, not a replacement).

## Capabilities

### New Capabilities
- `contract-context-api`: a JSON HTTP API, documented under `/api/docs`, exposing the contract-generation context per contract class - template + slot instructions (with slot-ontology coverage), per-type 法律法规, the tag vocabulary, the clause catalog, the canonical section order, and per-type rubric/prompt pointers - plus a `generate` endpoint that runs the existing tag-driven assembly. Built for external agents to draft or assemble contracts over plain HTTP.

### Modified Capabilities
<!-- None. The new router is added in src/web/app.py alongside the existing api router; no existing endpoint or capability changes. -->

## Impact

- **New code**: `src/web/routes/contract_context.py` (the router); a thin response-shaping helper module (or section in `routes/contract_context.py`) that projects service-function output into the bundle/clause-catalog shapes. DB-backed endpoints (laws survey, tags, clauses, generate) take `db: Path = Depends(get_db)` like the existing `api.py` routes.
- **New tests**: `tests/test_contract_context_api.py` - one test per endpoint (list, bundle, slots+ontology, laws, tags, clauses filter/paginate, generate markdown/docx, unknown-type 404, coherence-failure 422).
- **Modified code**: `src/web/app.py` - `app.include_router(contract_context.router)` in the lazy-include block (or top-level, since it has no optional dependency).
- **Dependencies**: none new - reuses FastAPI/Jinja already present.
- **Data**: reads existing committed template registry (`src/contracts/data/contracts.json`), bundled law-info seed, and the prod `law_bench` DB (clauses, law_info, tag_dims). No new seed data.
- **Operations**: endpoints available whenever the web app runs; the remote NodePort (`http://23.144.68.246:30820/api/docs`) gains the new paths after the next deploy. No auth in v1 (matches the existing open MCP/HTML posture).
- **Out of scope**: auth/rate-limiting (documented as a follow-up, not v1), streaming/SSE generation, in-place slot filling / mail-merge, new contract types or new clause data, and any change to the assembly precedence or coherence gate.
