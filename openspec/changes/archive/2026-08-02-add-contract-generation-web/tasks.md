## 1. Setup

- [x] 1.1 Create the `src/contracts/` package directory with an empty `__init__.py` placeholder
- [x] 1.2 Create `src/contracts/data/` for the committed template registry (`contracts.json`)

## 2. Contract templates + slot instructions

- [x] 2.1 Implement `src/contracts/templates.py`: `list_contract_types()` reading `output/law_info/contract_types.json` (returns `[{key, zh}]` in file order) and `get_template(contract_type)` returning `{type, zh_name, body, slots}` where `slots` is the de-duplicated `{{slot}}` names in `body` via `src.docs.find_slots`; raise `src.eval.errors.NotFoundError` for unknown types
- [x] 2.2 Implement `src/contracts/slots.py`: the `SlotInstruction` model (`name`, `label`, `description`, `example`, `required`) and `get_slot_instructions(contract_type)` returning the per-type instruction list; raise `NotFoundError` for unknown types
- [x] 2.3 Author `scripts/seed_contract_templates.py` that generates a standard contract skeleton (parties, subject matter, rights/obligations, term, payment, breach, dispute resolution, governing law, signatures) with per-type `{{slot}}` placeholders and a matching slot-instruction manifest for all 41 types, writing `src/contracts/data/contracts.json` (`[{key, zh, body, slot_instructions:[...]}]`)
- [x] 2.4 Run the seed script and commit `src/contracts/data/contracts.json`; have `templates.py`/`slots.py` load it
- [x] 2.5 Add a consistency check (used by tests) asserting every template slot has exactly one instruction and no instruction references an absent slot

## 3. Per-contract-class legal extraction

- [x] 3.1 Implement `src/contracts/legal.py`: `extract_laws_for_type(contract_type)` that reads `output/law_info/{deepseek,doubao}/<type>.md`, builds `{contract_type, source, content}` items, calls `src.eval.legal_refs.extract_references`, and returns `[{name, category, category_zh, sources}]` for laws referencing that type; raise `NotFoundError` for unknown types; allow the source directory to be overridden (default `output/law_info/`)

## 4. DOCX/PDF generation facade

- [x] 4.1 Implement `src/contracts/generator.py`: `generate_contract(contract_type, *, format="pdf", out_dir=None)` that resolves template + instructions + laws, builds the DOCX via `src.docs.create_docx(body, <out_dir>/<type>.docx, title=zh_name)` with `slots=None` (highlighted fillable placeholders), converts via `src.docs.docx_to_pdf` for `pdf`/`both`, and returns `{docx_path, pdf_path, slots, instructions, laws}` (unset formats -> `None`); default `out_dir` = `output/contracts`; raise `NotFoundError` for unknown types
- [x] 4.2 Confirm the generated DOCX's slots (via `src.docs.find_slots`) match the template manifest slots

## 5. CLI tool

- [x] 5.1 Implement `src/contracts/cli.py` (argparse): positional `contract_type` (required unless `--all`), `--format {pdf,docx,both}` (default `pdf`), `--all`, `--out DIR` (default `output/contracts`); on success print the generated path(s); on `NotFoundError` print an error naming the type to stderr and exit 1
- [x] 5.2 Add `src/contracts/__main__.py` invoking `cli.main()` so `python -m src.contracts` works

## 6. Public API

- [x] 6.1 Re-export the public API from `src/contracts/__init__.py`: `list_contract_types`, `get_template`, `get_slot_instructions`, `extract_laws_for_type`, `generate_contract`

## 7. Web exposure

- [x] 7.1 Implement `src/web/routes/contracts.py` (APIRouter, `tags=["contracts"]`): `GET /contracts` (list), `GET /contracts/{type}` (detail via `get_template` + `get_slot_instructions` + `extract_laws_for_type`, 404 on unknown), `GET /contracts/{type}/download/{format}` (generate via `generate_contract` then `FileResponse`; 404 unknown type, 400 unsupported format)
- [x] 7.2 Create `src/web/templates/contracts_list.html` and `contract_detail.html` extending `base.html`; detail page renders the body with `render_markdown`, lists each slot with its instruction, groups 法律法规 by `CATEGORY_ORDER`/`CATEGORY_ZH`, and shows DOCX/PDF download links
- [x] 7.3 Wire the `contracts` router into `src/web/app.py` via the existing lazy-include block; add a `/contracts` nav link in `src/web/templates/base.html`

## 8. Tests

- [x] 8.1 `tests/test_contract_templates.py`: `list_contract_types` (41 entries, order); `get_template` (fields + slots, `NotFoundError`); `get_slot_instructions` (coverage == template slots, fields populated); the slot/instruction consistency check across all 41 types; `extract_laws_for_type` (non-empty, fields, `NotFoundError`)
- [x] 8.2 `tests/test_contract_templates.py` generation: `generate_contract` produces `.docx`/`.pdf` under `output/contracts`, returns correct paths, `docx_path`/`pdf_path` are `None` for unrequested formats, generated DOCX contains highlighted `{{slot}}` placeholders (skip PDF assertions when `soffice` absent)
- [x] 8.3 `tests/test_contract_templates.py` CLI: `python -m src.contracts sale --format docx` exits 0 and prints a path; `--all --format docx` generates a `.docx` for every type; an unknown type exits non-zero
- [x] 8.4 `tests/test_contract_web.py`: `GET /contracts` lists all types; `GET /contracts/sale` shows template/slots/instructions/法律法规 + download links; `GET /contracts/does_not_exist` returns 404; `GET /contracts/sale/download/docx` streams a docx; `download/rtf` returns 400; `download` for unknown type returns 404 (skip PDF download test when `soffice` absent)
- [x] 8.5 Run `uv run pytest tests/test_contract_templates.py tests/test_contract_web.py` and confirm all tests pass

## 9. Verification

- [x] 9.1 Run `uv run python -c "from src.contracts import list_contract_types, get_template, get_slot_instructions, extract_laws_for_type, generate_contract; print('imports ok')"` to confirm the public API imports cleanly
- [x] 9.2 Run `uv run python -m src.contracts sale --format both` and verify `output/contracts/sale.docx` and `output/contracts/sale.pdf` are created and the printed paths match
- [x] 9.3 Run `uv run uvicorn src.web.app:app --port 8010` and verify `/contracts`, `/contracts/sale`, and `/contracts/sale/download/pdf` render/download correctly
- [x] 9.4 Run `openspec validate add-contract-generation-web` and confirm the change is valid

## 10. Type-specific contract bodies (LLM + 法律法规)

- [x] 10.1 Add `normalize_body` to `src/contracts/templates.py` (strip code fence + H1 title, remove unknown `{{slot}}` tokens, append missing required slots)
- [x] 10.2 Add `REQUIRED_SLOTS` + `default_slot_instructions(zh)` to `src/contracts/slots.py` as the single source of truth; refactor `scripts/seed_contract_templates.py` to use them
- [x] 10.3 Fix `src/contracts` to read the canonical bundled law_info under `src/eval/seed/law_info/` (not the gitignored `output/law_info`)
- [x] 10.4 Add `scripts/generate_contract_templates_llm.py`: per type, feed the Doubao+DeepSeek 法律法规 answers to the doubao (`DRAFTER_MODEL`) LLM, normalize, cache to `src/contracts/data/_llm_bodies/`, refresh `contracts.json`
- [x] 10.5 Run the generator for all 41 types; verify each body is type-specific and `check_slot_consistency` is clean
- [x] 10.6 Update `tests/test_contract_templates.py` (relax slot-order assertion to set equality; add `normalize_body` test) and re-run the suite + `openspec validate`

## 11. Web: generation-principle section

- [x] 11.1 Add a "生成原理" panel to `/contracts/{type}` (data source, LLM drafting, slot mechanism, DOCX/PDF generation, consistency guarantee) and a short note on `/contracts`; assert it in `test_contract_web.py`
