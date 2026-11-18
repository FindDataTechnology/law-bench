## Why

The repo already collects per-contract-type 法律法规 surveys from Doubao and DeepSeek (`output/law_info/`, 41 contract classes, each with a `doubao/*.md` and `deepseek/*.md` answer) and ships a standalone DOCX/PDF + slot module (`src/docs/`). But the two never meet: there is no **tool** that takes a contract class, extracts its 法律法规 from the LLM answers, and turns out a formatted, fillable contract **PDF** (and DOCX) with named **slots** and **slot instructions**. So the deliverable a legal counterparty actually expects cannot be produced end-to-end, and none of it is reachable from the web app. This change delivers that tool - extract the per-contract-class 法律法规 from the Doubao+DeepSeek answers and generate fillable contract PDFs/DOCX with slots and per-slot instructions - and then exposes the contracts, slots, slot instructions, and legal information on the web.

## What Changes

- **New `src/contracts/` package + CLI tool** (`python -m src.contracts`) - the extraction-and-generation engine. For a given contract class (or `--all` 41 classes) the tool:
  - **extracts** the 法律法规 from the Doubao+DeepSeek answers (reusing `src/eval/legal_refs.extract_references`);
  - **builds** the contract template (Markdown body with `{{slot}}` placeholders, reusing the `document-generation` slot token model) together with a **slot-instruction manifest** (`name`, `label`, `description`, `example`, `required` per slot);
  - **generates** the `.docx` and `.pdf` via the existing `src/docs/` module (`create_docx`, `docx_to_pdf`/`create_pdf`), leaving slots as highlighted, fillable placeholders;
  - prints the output file paths and a JSON summary (slots, instructions, extracted laws).
  - Template definitions are keyed by the 41 types in `output/law_info/contract_types.json`.
- **New web capability** (`src/web/routes/contracts.py` + Jinja templates):
  - `/contracts` - browse the contract classes.
  - `/contracts/{type}` - view the template content, the slots with their instructions, the per-type 法律法规, and download links for the generated DOCX/PDF.
  - `/contracts/{type}/download/{format}` - stream the generated `.docx` or `.pdf`.
  - Wired into `src/web/app.py` alongside the existing `law_info`/`pages` routers; the web layer calls the same `src/contracts/` API the CLI uses, so generation is shared, not duplicated.
- **No changes** to `document-generation` (consumed as-is), `contract-drafting-pipeline`, scoring/judging, or the existing `law-info-web` / `/law-references` pages (linked, not modified).

## Capabilities

### New Capabilities
- `contract-templates`: a tool that, per contract class, extracts the 法律法规 from the Doubao+DeepSeek answers, builds a slot-based contract template with a per-slot instruction manifest, and generates DOCX/PDF deliverables via the `document-generation` module - exposed as a CLI (`python -m src.contracts`) and a reusable Python API.
- `contract-templates-web`: web UI to browse contract classes, view a contract's template / slots / slot-instructions and its 法律法规, and download the generated DOCX/PDF.

### Modified Capabilities
<!-- None. document-generation is consumed unchanged; law-info-web is linked, not modified. -->

## Impact

- **New code**: `src/contracts/` package (`__init__.py`, `templates.py` - template + slot definitions, `slots.py` - slot-instruction model, `legal.py` - per-type 法律法规 extraction, `generator.py` - docx/pdf generation facade, `cli.py`/`__main__.py` - the CLI tool); `src/web/routes/contracts.py`; new templates `contracts_list.html`, `contract_detail.html`.
- **New tests**: `tests/test_contract_templates.py` (extraction, template + slot-instruction model, docx/pdf generation, CLI), `tests/test_contract_web.py` (routes + download).
- **Modified code**: `src/web/app.py` (include the new `contracts` router via the existing lazy-include pattern); `src/web/templates/base.html` (nav link to `/contracts`).
- **Dependencies**: none new - reuses `python-docx`, the `libreoffice` PDF backend, and FastAPI/Jinja already present.
- **Data**: contract template + slot-instruction definitions are committed source data (per type); generated DOCX/PDF are artifacts under `output/contracts/`.
- **Operations**: `python -m src.contracts <type>` runs locally and in-container (PDF needs the existing `libreoffice` image layer); `/contracts*` routes available whenever the web app runs.
- **Out of scope**: auto-drafting contracts via the CrewAI pipeline, slot validation against an external schema, in-browser slot-filling/form-submission, and mail-merge.
