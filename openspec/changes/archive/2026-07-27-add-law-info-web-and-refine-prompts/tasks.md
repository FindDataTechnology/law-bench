## 1. Bundle the law_info data into the repo

- [x] 1.1 Copy `output/law_info/doubao/*.md` (41 files) to `src/eval/seed/law_info/doubao/`
- [x] 1.2 Copy `output/law_info/deepseek/*.md` (41 files) to `src/eval/seed/law_info/deepseek/`
- [x] 1.3 Copy `output/law_info/contract_types.json` to `src/eval/seed/law_info/contract_types.json`
- [x] 1.4 Add `src/eval/seed/law_info/__init__.py` (empty package marker) and verify the 82 files + JSON are committed (not gitignored)

## 2. `law_info` table + schema

- [x] 2.1 Add `CREATE TABLE IF NOT EXISTS law_info (...)` with columns `id BIGINT GENERATED ALWAYS AS IDENTITY PK`, `contract_type TEXT NOT NULL`, `source TEXT NOT NULL`, `zh_name TEXT`, `content TEXT NOT NULL`, `created_at TIMESTAMPTZ DEFAULT now()`, and `UNIQUE(contract_type, source)` to the shared `SCHEMA` in `scripts/extract_harbor_rules.py`
- [x] 2.2 Add the same `CREATE TABLE IF NOT EXISTS law_info (...)` to `src/eval/store.py::ensure_schema` so the runtime/self-heal path also establishes it
- [x] 2.3 Verify both schema paths create the table idempotently on a fresh DB (no error on re-run)

## 3. `seed_law_info.py` seeder

- [x] 3.1 Create `scripts/seed_law_info.py` that reads `src/eval/seed/law_info/{doubao,deepseek}/<type>.md` + `contract_types.json`, calls `create_schema`, and upserts one row per `(contract_type, source)` matching on the unique pair (UPDATE content/zh_name if exists, else INSERT)
- [x] 3.2 Ensure the seeder is idempotent (re-run leaves row count at 82, no duplicates) and never touches `rubrics`/`criteria`/`prompts`/`eval_runs`
- [x] 3.3 Run `uv run python scripts/seed_law_info.py` and confirm 82 rows (41 types × 2 sources) are seeded

## 4. `src/eval/law_info.py` read module

- [x] 4.1 Create `src/eval/law_info.py` with `list_law_info_types(db)` (returns the 41 types with zh_name + per-source presence) and `get_law_info(type, db)` (returns `{type, zh_name, doubao, deepseek}` with both content bodies, or raises a not-found)
- [x] 4.2 Use the borrowed-connection pattern from `src/eval/db.py` (do not close the web-layer connection)
- [x] 4.3 Handle an unknown `type` with a clear not-found error (map to a 404-friendly state in the route)

## 5. Markdown rendering dependency

- [x] 5.1 Promote `markdown-it-py` to a direct dependency in `pyproject.toml` (already transitive via `rich` in `uv.lock`)
- [x] 5.2 Add a small render helper (e.g. `src/web/markdown_render.py` or a function in `src/eval/law_info.py`) that renders markdown to HTML with `markdown-it-py` and falls back to escaped raw text on exception
- [x] 5.3 Run `uv lock` / `uv sync` to refresh the lockfile

## 6. Law-info web routes + templates

- [x] 6.1 Create `src/web/routes/law_info.py` with `GET /law-info` (list 41 types by Chinese name, linked) and `GET /law-info/{type}` (Doubao + DeepSeek side-by-side, markdown-rendered), `tags=["law-info"]`, reading via `get_db()` + `src/eval/law_info.py`
- [x] 6.2 Create `src/web/templates/law_info_list.html` and `law_info_detail.html` (two-column side-by-side, each section labeled by source), extending `base.html`
- [x] 6.3 Register the `law_info` router in `src/web/app.py` inside the existing `try/except ImportError` HTML-routes block alongside `pages.router`
- [x] 6.4 Verify `/law-info` lists 41 types and `/law-info/sale` renders both sources side-by-side; verify an unknown type renders a not-found state without an unhandled exception

## 7. Legal references extractor + index page + doc

- [x] 7.1 Create `src/eval/legal_refs.py` with a pure `extract_references(items) -> list[dict]` that parses law names (regex over `《...》` and common statute/interpretation patterns), deduplicates by canonical name, categorizes (`core_law` / `judicial_interpretation` / `special_statute` / `procedural` / `other`), and tags each with the `(contract_type, source)` pairs it appeared in
- [x] 7.2 Add `GET /law-references` to `src/web/routes/law_info.py` that loads all `law_info` rows from the DB, runs `extract_references`, and renders a filterable (by source and by contract type) categorized index
- [x] 7.3 Create `src/web/templates/law_references.html` extending `base.html`
- [x] 7.4 Create `scripts/extract_legal_references.py` CLI that reads the bundled markdown via `extract_references` and writes a deterministic `docs/legal_references.md` (deduplicated, categorized); verify re-running produces an identical file
- [x] 7.5 Verify `/law-references` lists every referenced law once, categorizes them, and that source/type filters work

## 8. Law-refined v2 drafting prompts

- [x] 8.1 For each of the 41 contract types, author a `draft_<type>_v2` prompt entry in `scripts/seed_contract_prompts.py` (`purpose = drafting`, `source = local`, `prompt_type = law-refined`, `contract_type = type_key`) whose `content` names the governing statutes/interpretations/article ranges drawn from that type's `doubao/<type>.md` + `deepseek/<type>.md`
- [x] 8.2 Ensure the v2 entries are appended to `PROMPTS` without modifying any baseline `draft_<type>` entry (names differ)
- [x] 8.3 Run `uv run python scripts/seed_contract_prompts.py` and confirm 41 new `draft_<type>_v2` rows with `prompt_type = law-refined`; confirm baseline rows are unchanged and re-running is idempotent

## 9. Law-refined v2 contract rubrics

- [x] 9.1 For each of the 41 contract types, author a `contract_<type>_v2` rubric entry in `scripts/seed_contract_rubrics.py` (`source = local`, `context = contract`) = 4 shared base criteria + 4-6 type-specific criteria whose `guidance` cites the correct governing statutes/interpretations from the law_info survey
- [x] 9.2 Ensure the v2 entries are appended to `RUBRICS` without modifying any v1 `contract_<type>_v1` rubric
- [x] 9.3 Run `uv run python scripts/seed_contract_rubrics.py` and confirm 41 new `contract_<type>_v2` rubrics; confirm v1 rubrics are unchanged and re-running is idempotent

## 10. i18n updates

- [x] 10.1 Add `nav.law_info` and `nav.law_references` keys to both `zh` and `en` in `src/web/i18n.py::LOCALES`
- [x] 10.2 Add `law-refined` -> `法律精修` (zh) and `Law-refined` (en) to `LABELS["prompt_type"]` in both locales
- [x] 10.3 Extend `title_for_prompt` / `title_for_rubric` in `src/web/i18n.py` to recognize a trailing `_v<N>`: `draft_<type>_v<N>` -> `<ct>起草 v<N>`; `contract_<type>_v<N>` -> `<ct>评价规则 v<N>` (so v1 rubrics now render `...评价规则 v1` and v2 render `...评价规则 v2`)
- [x] 10.4 Add the two nav links to `src/web/templates/base.html`

## 11. Tests

- [x] 11.1 Create `tests/test_law_info.py`: seeder idempotency, schema creation via both paths, 82 rows seeded (41×2), no touch of other tables
- [x] 11.2 Create `tests/test_law_info_web.py`: `/law-info` lists 41 types; `/law-info/sale` renders both sources side-by-side; unknown type renders not-found; markdown renders to HTML
- [x] 11.3 Create `tests/test_legal_references.py`: `extract_references` deduplicates, categorizes, tags `(type, source)`; unmatched names land in `other`; the generated `docs/legal_references.md` is deterministic
- [x] 11.4 Update `tests/test_i18n.py`: assert `prompt_type` parity now includes `law-refined`; assert `draft_<type>_v2` -> `<ct>起草 v2` and `contract_<type>_v1` -> `<ct>评价规则 v1` (updated title rule); assert the two new nav keys exist in both locales
- [x] 11.5 Update/add tests for the v2 seeders: `draft_<type>_v2` prompts seeded with `law-refined` and baseline untouched; `contract_<type>_v2` rubrics seeded with correct statute citations and v1 untouched
- [x] 11.6 Run the full suite (`uv run pytest`) and confirm everything passes

## 12. Final verification

- [x] 12.1 Run `openspec validate add-law-info-web-and-refine-prompts` and confirm the change is valid
- [x] 12.2 Run all seeders end-to-end on a fresh DB (`extract_harbor_rules` → `seed_contract_rubrics` → `seed_contract_prompts` → `seed_law_info`) and confirm counts: 82 law_info rows, 41 v2 prompts, 41 v2 rubrics, alongside the existing baseline/harbor rows
- [x] 12.3 Smoke-test the web locally: `/law-info`, `/law-info/sale`, `/law-references` render; nav links present in both locales; v2 prompts/rubrics appear in the listings with versioned titles
