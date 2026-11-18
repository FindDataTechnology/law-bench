## Why

The contract-drafting crew currently delivers contracts only as Markdown files (`output/*.md`, `templates/*.md`). There is no way to produce the actual deliverable formats a legal counterparty expects — formatted **DOCX** and **PDF** — nor any mechanism to leave named **slots** (party names, dates, amounts, jurisdiction) that a user fills in before signing. This change adds a focused Python module that renders contract content to DOCX, injects/fills named slots, and converts the DOCX to PDF, giving the pipeline real document output.

## What Changes

- **New `src/docs/` module** providing the requested functions:
  - `create_docx(...)` — build a `.docx` from Markdown/structured contract content (headings, paragraphs, lists, bold), optionally injecting named slots as visible placeholders or pre-filled values.
  - `add_slot(...)` — insert a single named slot into a DOCX (for building templates programmatically), rendered as a findable, highlighted placeholder.
  - `fill_slots(...)` — replace slot placeholders with concrete values in an existing DOCX (accepts a path or an open `Document`).
  - `docx_to_pdf(...)` — convert a `.docx` to `.pdf` via a headless converter backend.
  - `create_pdf(...)` — convenience wrapper: `create_docx` then `docx_to_pdf`.
- **Slot model**: slots are named placeholders using a `{{slot_name}}` token syntax. At generation time a `slots: dict[str, str | None]` mapping either fills a slot with its value or leaves a clearly-marked placeholder (e.g. `{{slot_name}}`) so the user can fill it in Word. `fill_slots` substitutes placeholders in an already-generated DOCX.
- **PDF conversion backend**: headless **LibreOffice** (`soffice --headless --convert-to pdf`) as the default — portable across the dev macOS machine and the deployed Linux/k3s containers with no MS Word dependency. The converter is behind an interface so `docx2pdf` (Word/AppleScript) can be swapped in for local dev if desired.
- **New dependency**: `python-docx` (added to `pyproject.toml`). **New system dependency**: `libreoffice` (added to `Dockerfile` for the container image).
- **No changes** to the crew, `contract-drafting-pipeline`, scoring/judging, or the web app. Wiring the new module into the drafting pipeline/runtime is explicitly out of scope (a follow-up); this change only delivers the standalone functions.

## Capabilities

### New Capabilities
- `document-generation`: render contract content to formatted **DOCX**, inject and fill named **slots** (placeholders for user-supplied information), and convert DOCX to **PDF** via a headless converter — exposed as a standalone Python module (`src/docs/`).

### Modified Capabilities
<!-- None. The drafting pipeline's requirements are unchanged; consuming this module at runtime is a follow-up. -->

## Impact

- **New code**: `src/docs/` package — `generator.py` (DOCX creation + slot injection/fill), `converter.py` (DOCX→PDF), `slots.py` (slot token model + paragraph-level replacement helpers), and `__init__.py` re-exporting the public API.
- **New tests**: `tests/test_docs_generator.py`, `tests/test_docs_converter.py`, `tests/test_docs_slots.py`.
- **Modified code**: `pyproject.toml` (add `python-docx`); `Dockerfile` (install `libreoffice` for headless PDF conversion in the container).
- **Dependencies**: `python-docx>=1.1` (Python package); `libreoffice` (system binary, container-only — on macOS dev it is expected to be installed via `brew install --cask libreoffice` or already present).
- **Operations**: functions are importable (`from src.docs import create_docx, docx_to_pdf, create_pdf, fill_slots, add_slot`); PDF conversion in the container requires the `libreoffice` layer added to the image.
- **Out of scope**: pipeline/runtime integration (auto-producing DOCX/PDF from a drafted contract), web UI endpoints for document export, slot validation against a contract schema.
