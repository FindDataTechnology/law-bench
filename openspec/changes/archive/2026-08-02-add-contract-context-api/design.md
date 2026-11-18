## Context

The repo collects, per contract class (43 types), everything needed to draft a contract: a slot-based template skeleton + slot-instruction manifest (`src/contracts/`, file-backed via `data/contracts.json`), per-type 法律法规 surveys from Doubao+DeepSeek (`src/eval/law_info` table + `src/contracts/legal.extract_laws_for_type` over bundled markdown), a tag-driven clause-assembly engine (`src/clauses/assemble.generate_contract_assembled`: per-section override `custom > tagged > base` + a strict coherence gate), a controlled tag vocabulary per type (`src/clauses/tags`: universal dims `stance/strength/risk/mandatory/source` + type-specific dims like `scenario`, loaded from the `tag_dims` table), and a slot ontology (`src/contracts/slot_ontology`: ~270 canonical slot concepts with role-prefixed aliases, so `{{seller_address}}` resolves to the `address` concept). All of this is exposed over **MCP** (`fd-coding-law-bench-mcp/` - the full agent surface, but only for MCP clients) and partly over **HTML** (`/contracts/{type}` renders template + slots + laws to a page, `include_in_schema=False`). The **JSON HTTP API** under `/api` (documented at `/api/docs`) covers only the eval side: rubrics, prompts, compare, harbor, search - 20 endpoints, **none** for contracts, slots, laws, tags, clauses, or generation. So a plain-HTTP agent cannot reach any of it. Constraints: no new Python deps; DB-backed reads must reuse the existing `Depends(get_db)` connection-borrowing pattern; the assembly model and coherence gate are stable and must not change.

## Goals / Non-Goals

**Goals:**
- A documented JSON API under `/api/docs` exposing, per contract class: the template + slot instructions (with slot-ontology coverage), structured 法律法规 refs (+ optional full survey markdown), the tag vocabulary, the clause catalog (filterable/paginated), the canonical section order, and per-type rubric/prompt pointers.
- A `POST /api/contracts/{type}/generate` endpoint that runs the existing tag-driven assembly, defaulting to `markdown` output for agents, with `docx`/`pdf` returning download URLs.
- Every endpoint is a thin route over an existing service function - no new business logic, no duplication of the assembly/extract/instruct code.

**Non-Goals:**
- Auth, API keys, or rate-limiting in v1 (the existing MCP and HTML surfaces are already open on a bare-IP NodePort; v1 matches that posture, with rate-limiting tracked as a follow-up).
- Streaming/SSE generation; large compares already warn to use the CLI, and the same applies here.
- In-place slot filling, mail-merge, or form submission - slots stay highlighted, fillable placeholders.
- New contract types, new clauses, or new seed data - this only *exposes* what exists.
- Any change to the assembly precedence (`custom > tagged > base`), the coherence gate, `document-generation`, or the MCP server.
- Replacing the HTML `/contracts` pages or the MCP tools - the JSON API is a parallel surface.

## Decisions

### D1: Bundle + focused complements (not pure granular REST)
**Choice**: A comprehensive `GET /api/contracts/{type}` returns the full context bundle in one call; focused endpoints (`/slots`, `/laws`, `/tags`, `/clauses`) return projections for lightweight/cacheable access; `POST /generate` runs assembly.
**Rationale**: The headline use case is "an agent gathers everything it needs in one round trip" - that is the comprehensive API the user asked for. Pure granular REST would force N round trips for a draft. The focused endpoints serve the agent that already cached the bundle and only wants to refresh one slice, and they keep individual payloads small.
**Alternatives**: Pure granular REST (more round trips, but more cacheable per-resource) - rejected as the primary shape; a single mega-endpoint returning clause bodies too (rejected - see D2).

### D2: Clauses - summary in the bundle, bodies via a dedicated paginated endpoint
**Choice**: The comprehensive bundle carries only a clause-availability summary (`{base: N, tagged: N, custom: N}`); actual clause bodies are fetched via `GET /api/contracts/{type}/clauses?scenario=&stance=&source=&limit=&offset=`.
**Rationale**: The clause corpus is ~6,369 rows; embedding all bodies in the bundle would make it hundreds of KB and let an agent bulk-scrape the corpus in 43 calls. A summary + on-demand filtered/paginated endpoint keeps the bundle lean and gives natural crawl control. The corpus is already fully exposed over MCP and HTML, so this is not new exposure - just shaped for HTTP.
**Alternatives**: Full clause bodies in the bundle (rejected - payload size, scrape blast radius); clause IDs only, no bodies (rejected - agent would need a second call per clause).

### D3: Slot API includes slot-ontology coverage, with a `source` per entry
**Choice**: `GET /api/contracts/{type}/slots` returns the union of (a) the type's manifest from `get_slot_instructions` and (b) for any `{{slot}}` in the template body not covered by the manifest, the ontology's `instruction_for_slot(name)`. Each entry carries `source: "registry" | "ontology" | "uncovered"`.
**Rationale**: Tagged/custom clauses carry role-prefixed variant slot names (`seller_address`, `buyer_name`) the basic 12-slot manifest doesn't explain. An agent filling those needs guidance; the ontology already has it. Surfacing `uncovered` slots flags data debt (a slot with no instruction anywhere) the same way the coherence gate does internally.
**Alternatives**: Slot API returns only the 12-entry manifest (rejected - leaves variant slots unexplained); resolve variants to canonical names silently (rejected - loses the `source` signal an agent needs to trust the instruction).

### D4: `generate` defaults to `docx`; markdown is opt-in
**Choice**: `POST /api/contracts/{type}/generate` takes `format: "docx" | "pdf" | "both" | "markdown"` (default `"docx"`, matching `generate_contract_assembled`'s own default). `markdown` returns `body_text` only (no file I/O). `docx`/`pdf`/`both` write the file under `output/contracts/` and return a `docx_url`/`pdf_url` for download. The response **always** includes `body_text`, so an agent that wants the text alongside the file gets it in one call.
**Rationale**: "Generate a contract" should produce the deliverable a counterparty expects - a `.docx` - not raw markdown; this also matches the existing service default, so the route is a thin pass-through. The `markdown` path remains available for agents that only want the body string. Carrying `body_text` regardless of format keeps the JSON response useful even when a binary is produced.
**Alternatives**: Default to `markdown` (rejected - "generate" should yield the document, and it diverges from the service default); stream the binary inline as base64 (rejected - bloats JSON, breaks caching).

### D5: Law refs in the bundle; full survey markdown only in `/laws`
**Choice**: The bundle's `laws` field carries structured `refs: [{name, category, category_zh, sources}]` only. The full Doubao+DeepSeek survey markdown is returned by `GET /api/contracts/{type}/laws` (`{refs, survey_md: {doubao, deepseek}}`).
**Rationale**: The structured refs are the compact, agent-actionable signal (which laws apply). The survey markdown is large and supplementary (the LLM reasoning). Splitting keeps the bundle reasonable while still offering the full text on demand.
**Alternatives**: Survey markdown in the bundle (rejected - bloats every bundle call); survey markdown dropped entirely (rejected - some agents want the source reasoning).

### D6: Per-type rubric + prompts as pointers, not full bodies
**Choice**: The bundle carries `rubric: {name}` (the latest-version rubric for the type, e.g. `contract_sale_v3`, or `null`) and `prompts: [{name, purpose}]` (prompts whose `contract_type` matches). The agent fetches full criteria/content via the existing `GET /api/rubrics/{name}` and `GET /api/prompts/{name}`.
**Rationale**: Rubric criteria and prompt content can be large; embedding them would duplicate data already served by `/api/rubrics` and `/api/prompts` and bloat the bundle. A pointer signals "this exists, fetch it if you want it."
**Alternatives**: Embed full rubric + prompts in the bundle (rejected - duplication, payload); omit them (rejected - an agent that wants to self-evaluate or follow a known-good drafting prompt should know they exist).

### D7: Thin routes over existing service functions; DB via `Depends(get_db)`
**Choice**: No new business logic. Each route calls the existing service function (`get_template`, `get_slot_instructions`, `extract_laws_for_type`, `get_law_info`, `tag_vocab_list`, `list_clauses`, `generate_contract_assembled`, `slot_ontology.instruction_for_slot`) and shapes the result. DB-backed reads take `db: Path = Depends(get_db)` exactly like `src/web/routes/api.py`.
**Rationale**: The service layer is already correct and tested; the gap is purely HTTP exposure. Reusing it keeps the JSON and MCP/HTML surfaces from diverging.
**Alternatives**: A separate service layer for the JSON API (rejected - duplication risk); file-only reads with no DB (rejected - law_info survey, clauses, tag_dims are DB-backed).

### D8: Open, no auth in v1
**Choice**: No authentication or rate-limiting on the new endpoints in v1.
**Rationale**: The existing MCP server and HTML pages are already open on the bare-IP NodePort (`23.144.68.246:30820`), and the clause/law corpus is intentionally public. v1 matches that posture so agents can be built immediately. Rate-limiting and an optional API-key tier are tracked as a follow-up (not blocking) for when abuse becomes a concern.
**Alternatives**: Require a static API key from day one (rejected - friction for the "build agents" use case the user wants to enable); defer the whole API until auth lands (rejected - defers the value).
