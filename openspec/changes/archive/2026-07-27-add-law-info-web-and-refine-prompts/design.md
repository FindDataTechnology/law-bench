## Context

The repo already seeds 41 per-contract-type drafting prompts (`scripts/seed_contract_prompts.py`) and 41 rubrics (`scripts/seed_contract_rubrics.py`) - 19 《民法典》 types + 22 practical types. Their legal citations are authored from general knowledge. A new data asset exists: `output/law_info/{doubao,deepseek}/<type>.md` - 82 detailed, source-attributed 法律法规 surveys (one per type per LLM) with governing statutes, judicial interpretations, and article ranges. Two constraints shape the design:

1. **`output/` is gitignored** (verified: `git check-ignore output/law_info/sale.md` → `IGNORED`). The containerized web app (deployed as `law-bench` on k3s) has no access to `output/`. To display this data in the web, it must be committed to the repo.
2. **The DB is Postgres**, the single runtime source of truth. The web layer migrated off filesystem paths (`get_db()` returns a connection, not a `Path`). Schema is created by two paths: `scripts/extract_harbor_rules.py::create_schema` (used by seeders; creates `rubrics`/`criteria`/`prompts`) and `src/eval/store.py::ensure_schema` (used by the runtime; creates the eval tables + additive columns). The container runs a harbor self-heal on startup that calls `create_schema`.

The system already supports `prompt_type` variant lineage (`baseline`, `experimental`) and A/B compare runs (`compare_runs` + `eval_runs` snapshot columns). Rubrics use `contract_<type>_v1` naming. `markdown-it-py` is already in `uv.lock` (transitive via `rich`). `data-label-i18n` owns the `prompt_type` label catalog and the seeded-name display-title derivation (`draft_<type>` → `<ct>起草`, `contract_<type>_vN` → `<ct>评价规则`).

## Goals / Non-Goals

**Goals:**
- Surface all 82 law_info answers in the web, browsable by contract type with Doubao + DeepSeek side-by-side.
- Produce **law-refined v2 variants** (`draft_<type>_v2`, `contract_<type>_v2`) whose content is grounded in the law_info's specific statutes/interpretations/article ranges, **without touching the baseline v1** - so the compare feature can A/B test baseline vs law-refined.
- Deliver a consolidated, deduplicated, categorized 法律法规 index as both a web page (`/law-references`) and a committed doc (`docs/legal_references.md`).
- Keep all web data in Postgres (DB-backed law_info + aggregate), idempotent seeding, startup self-heal.

**Non-Goals:**
- Re-querying Doubao/DeepSeek for fresh law_info (the bundled markdown is the source of truth).
- Modifying baseline v1 prompts/rubrics (non-destructive; v1 is preserved).
- Vector/RAG search over law_info (that is `rag-search`'s scope; `/law-references` is a direct aggregate).
- Backfilling `law_info` provenance into `eval_runs` snapshots.

## Decisions

### D1. Bundle the markdown into the repo and seed it into a new `law_info` table (DB-backed display)
Commit the 82 files under `src/eval/seed/law_info/{doubao,deepseek}/<type>.md` + `contract_types.json` (mirrors the existing `src/eval/seed/harbor/` bundled-seed pattern). Add a `law_info` table and `scripts/seed_law_info.py` that reads the bundled markdown and upserts one row per `(contract_type, source)`.

- **Schema**: `id BIGINT GENERATED ALWAYS AS IDENTITY PK`, `contract_type TEXT NOT NULL`, `source TEXT NOT NULL` (`doubao`|`deepseek`), `zh_name TEXT`, `content TEXT NOT NULL`, `created_at TIMESTAMPTZ DEFAULT now()`, `UNIQUE(contract_type, source)`. Loose coupling - no FK to `rubrics`/`prompts` (matches the existing `contract_type` discipline).
- **Two schema paths**: add `CREATE TABLE IF NOT EXISTS law_info (...)` to the shared `SCHEMA` in `scripts/extract_harbor_rules.py` **and** to `src/eval/store.py::ensure_schema`, so both the seeder path and the runtime/self-heal path establish it idempotently.
- **Alternatives rejected**: (a) serve the bundled markdown as static files with no DB - rejected, breaks the idempotent-seed/self-heal pattern and gives no `zh_name` join for localized titles; (b) read `output/` at runtime - rejected, gitignored and absent from the container; (c) store the aggregate in a second table - rejected, derived data is recomputed (see D4).

### D2. Law-refined content as new v2 variants, baseline untouched
Append 41 `draft_<type>_v2` entries to `seed_contract_prompts.py::PROMPTS` (`prompt_type = "law-refined"`, `purpose = drafting`, `contract_type = type_key`) and 41 `contract_<type>_v2` entries to `seed_contract_rubrics.py::RUBRICS` (`source = local`, `context = contract`). The v2 content is authored by reading each type's `doubao/<type>.md` + `deepseek/<type>.md` and incorporating the named statutes (e.g. for `sale`: 民法典 595–647 条 + 法释〔2020〕17 号 + 法释〔2023〕13 号) into the prompt's mandatory-clause list and the rubric's type-specific criteria/guidance. v1 rows are never modified (upsert matches by name; `draft_<type>_v2` ≠ `draft_<type>`).

- **Rationale**: user-chosen; preserves baseline for A/B compare via the existing `prompt_type` lineage + `compare` feature; non-destructive.
- **Trade-off**: +41 prompt rows + 41 rubric rows. Acceptable; all idempotent.
- **Alternative rejected**: overwrite v1 in place - loses the baseline, no A/B.

### D3. Markdown rendering with `markdown-it-py`, server-side
Render `law_info.content` (markdown) to HTML server-side with `markdown-it-py` (already in `uv.lock`; promote to a direct dep in `pyproject.toml`). The content is first-party bundled (not user input at runtime), so the XSS surface is low; we render with default options and trust the bundled source. A `markupsafe.Markup` wrapper feeds the template. Raw text is the fallback if rendering raises.

- **Alternative rejected**: client-side rendering (e.g. marked.js) - rejected, would add a JS dep and flash unstyled content; server-side keeps the page a single HTML response consistent with the other Jinja pages.

### D4. Aggregated 法律法规 index: pure extractor, no second table
A pure function `src/eval/legal_refs.py::extract_references(items) -> list[dict]` parses law names (regex over `《...》` and common statute/interpretation patterns), deduplicates by canonical name, categorizes (`core_law` 核心法律 / `judicial_interpretation` 司法解释 / `special_statute` 专项法规 / `procedural` 程序法), and tags each with the `(contract_type, source)` it appeared in.

- **`/law-references` page**: loads all `law_info` rows from the DB, runs `extract_references` over their `content`, renders the categorized, filterable index. No second table - the aggregate is derived from `law_info.content`, recomputed per request (cheap enough for a management UI; cache with a module-level `lru_cache` keyed by a content hash if profiling demands).
- **`docs/legal_references.md`**: generated by `scripts/extract_legal_references.py` (CLI), which reads the bundled markdown (the canonical source) via the same `extract_references` function and writes the committed doc. Regenerate when the bundled markdown changes.
- **Rationale**: single extraction logic, two outputs (runtime page + committed doc); the DB stays the runtime source; the doc is a build artifact.
- **Alternative rejected**: store the aggregate as rows in a `legal_references` table - rejected, it's derived data that would need re-seeding whenever `law_info` changes; computing from `law_info.content` is simpler and always consistent.

### D5. i18n: new nav labels, `law-refined` prompt_type, `_v2` display titles
- Add `nav.law_info` and `nav.law_references` keys to `LOCALES` (zh/en parity) and two nav links in `base.html`.
- Add `law-refined` → `法律精修` (zh) / `Law-refined` (en) to `LABELS["prompt_type"]` (zh/en parity).
- Extend `title_for_prompt`/`title_for_rubric` regex to recognize a trailing `_v<N>`: `draft_sale_v2` → `买卖合同起草 v2`; `contract_sale_v2` → `买卖合同评价规则 v2`. The base contract-type label is looked up from the existing catalog (no new contract_type keys needed - the 41 keys already exist). The `prompt_type` column (`law-refined`) additionally disambiguates in the listings.

### D6. Web layering: a `law_info` router + a `src/eval/law_info.py` read module
- `src/eval/law_info.py`: `list_law_info_types(db)`, `get_law_info(type, db)` (returns both sources), DB read helpers using `src/eval/db.connect` (borrowed-conn pattern). Keeps routes thin, mirroring `src/eval/manage.py`.
- `src/web/routes/law_info.py`: `GET /law-info`, `GET /law-info/{type}`, `GET /law-references` - Jinja pages, `tags=["law-info"]`. Registered in `app.py` alongside `pages.router` (lazy import in the same `try/except ImportError` block, so the law-info UI is optional like the rest of the HTML UI).
- Templates: `law_info_list.html`, `law_info_detail.html` (two-column side-by-side), `law_references.html`.

## Risks / Trade-offs

- **[Bundle size] 82 markdown files (~500KB) committed to the repo** → acceptable; smaller than the existing `uv.lock`. Mitigation: none needed; git handles it fine.
- **[Extractor accuracy] Regex-based law-name extraction may miss or mis-categorize some statutes** → Mitigation: the extractor is tested against known samples (`sale.md` has well-known laws); unmapped names fall into an `other` bucket and are still listed (never dropped). The doc is regenerable, so corrections are cheap.
- **[v2 content authoring effort] 41 prompts + 41 rubrics must be hand-refined from the law_info** → Mitigation: this is the bulk of the implementation work; tasks.md breaks it into per-type or per-batch steps. The law_info is detailed enough to ground each refinement.
- **[markdown-it-py promotion] Adding a direct dep** → Mitigation: already in `uv.lock` transitively; promoting just makes the dependency explicit. No version risk.
- **[Two schema paths must both create `law_info`]** → Mitigation: add to both `SCHEMA` and `ensure_schema`; a parity check in tests asserts the table exists after each path runs on a fresh DB.
- **[Side-by-side rendering volume] `law_info_detail.html` renders two ~6KB markdown blobs** → Mitigation: trivial for server-side render; no pagination needed for 2 blocks.

## Migration Plan

1. Commit bundled markdown + `contract_types.json` under `src/eval/seed/law_info/`.
2. Add `law_info` table to both schema paths; add `seed_law_info.py`; run it.
3. Add `law_info.py` read module + `routes/law_info.py` + templates; register router; wire nav + i18n.
4. Add `legal_refs.py` extractor + `/law-references` page; add `extract_legal_references.py` CLI; generate `docs/legal_references.md`.
5. Append v2 entries to the prompt + rubric seeders; add `law-refined` label + `_v2` title derivation; run seeders.
6. Tests: `test_law_info.py` (seeder idempotency + schema), `test_law_info_web.py` (routes render both sources), `test_legal_references.py` (extractor dedup/categorization), update `test_i18n.py` (parity with new keys + `_v2` titles).
7. Rollback: revert the change; the `law_info`/v2 rows are additive - dropping the `law_info` table and the v2-named rows leaves v1/baseline fully functional. No destructive migration.

## Open Questions

- **Q1**: Should the v2 prompt/rubric content be authored per-type by hand (grounded in both sources) or templated from a shared skeleton with per-type statute lists? → leaning hand-authored per type for quality (the law_info differs meaningfully per type); tasks.md will treat per-type authoring as the unit of work.
- **Q2**: For `/law-references` filtering, is filter-by-source (doubao/deepseek) + filter-by-type sufficient, or do we also want a free-text search over law names? → leaning filter-by-source + filter-by-type + a simple law-name contains filter; defer full-text to `rag-search`.
