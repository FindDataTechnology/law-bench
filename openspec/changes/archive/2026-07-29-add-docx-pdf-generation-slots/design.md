## Context

The repo drafts Chinese legal contracts via a CrewAI pipeline and currently persists deliverables only as Markdown (`output/*.md`, `templates/*.md`). There is no DOCX or PDF output and no notion of fillable placeholders. The user wants a standalone Python module that (a) creates formatted `.docx` files from contract content, (b) supports named **slots** that can be filled with information, and (c) converts a `.docx` to `.pdf`. The project runs locally on macOS and is deployed to Linux/k3s containers (`Dockerfile`), so any system dependency must work in both. Nothing consumes this module yet; it is a pure addition.

## Goals / Non-Goals

**Goals:**
- A `src/docs/` module exposing `create_docx`, `add_slot`, `fill_slots`, `docx_to_pdf`, `create_pdf`.
- Render Markdown contract content (headings, paragraphs, bold/italic, bullet/numbered lists, horizontal rules) to a formatted DOCX using `python-docx`.
- A slot model: named `{{slot_name}}` tokens that are rendered as visually-marked placeholders or pre-filled values, plus programmatic slot insertion and filling.
- DOCX->PDF conversion that works on macOS dev **and** Linux containers without MS Word.
- A swappable converter backend so an alternative (e.g. `docx2pdf`) can be used where Word is available.
- Unit tests for generation, slots, and conversion.

**Non-Goals:**
- Pipeline/runtime integration (auto-producing DOCX/PDF from a drafted contract) - follow-up.
- Web UI / HTTP endpoints for document export.
- Slot validation against a contract schema; rich content-control (Word SDT/form fields); mail-merge.
- Full Markdown fidelity (tables, code blocks, images) - a lightweight renderer only.
- High-throughput/parallel PDF conversion pooling.

## Decisions

### D1: `python-docx` for DOCX creation and slot manipulation
**Choice**: `python-docx>=1.1`.
**Rationale**: The de-facto Python DOCX library; reads/writes `.docx`, exposes paragraphs/runs for precise slot injection. Pure-Python, no system binary.
**Alternatives**: `docxtpl` (Jinja2 templating over docx) - powerful but couples templates to a Jinja docx template file rather than Markdown content; `python-docx` keeps the Markdown-first flow and explicit slot API the user asked for. `pandoc` - heavyweight external binary; rejected.

### D2: Slot model - `{{slot_name}}` tokens, single-run, highlighted
**Choice**: Slots are `{{slot_name}}` tokens (regex `\{\{\s*([a-zA-Z_][\w-]*)\s*\}`). When `create_docx`/`add_slot` injects a slot, the token is written as **its own run** with a yellow highlight, so it is visually findable and unambiguous. `fill_slots` replaces tokens with caller values.
**Rationale**: Single-run tokens make replacement trivial and format-safe for our own documents; highlighting makes unfilled slots obvious to a human filling them in Word. `{{ }}` does not occur in Chinese legal prose, avoiding collisions.
**Alternatives**: Word content controls / SDT (true form fields) - `python-docx` has no first-class API, requiring fragile raw-XML manipulation; rejected for now (follow-up). Merge fields - require a data source and Word UI; rejected.
**Missing-value behavior**: `fill_slots` leaves tokens without a provided value untouched (lenient, enables partial fills) and returns the count filled; `strict=True` raises `SlotValueError` listing missing slots.

### D3: Lightweight Markdown -> DOCX renderer
**Choice**: A small in-module renderer mapping `#`/`##`/`###` -> Heading 1/2/3, `**bold**`/`*italic*` -> bold/italic runs, `- `/`* ` -> bullet list, `1. ` -> numbered list, `---` -> horizontal rule, blank-line-separated text -> paragraphs. Slot tokens inside any text are passed through to the DOCX (then highlighted/filled per D2).
**Rationale**: Reuses the project's existing Markdown contract format with no extra dependency.
**Alternatives**: `python-markdown` + custom walker - more faithful but heavier; deferred. `mistune` - same trade-off. The lightweight renderer covers the contract structures in `templates/*.md`.

### D4: PDF conversion via headless LibreOffice (default backend)
**Choice**: Default backend is `soffice --headless --convert-to pdf --outdir <dir> <file.docx>`, invoked as a subprocess, with `-env:UserInstallation=file:///tmp/lo-profile-<pid>` to avoid profile/lock collisions in headless/container runs.
**Rationale**: Portable across macOS and Linux containers, no MS Word dependency, high-fidelity DOCX rendering. The project already deploys to Linux/k3s where Word is unavailable.
**Alternatives**:
- `docx2pdf` - uses Word (COM/AppleScript); unusable in headless Linux containers. Kept as an **optional** alternative backend for local dev where Word exists.
- `reportlab`/`fpdf2` - generate PDF from scratch, i.e. reimplement DOCX layout in PDF; does not satisfy "transfer docx to pdf" and duplicates rendering. Rejected.
- `pandoc` md->pdf - needs a LaTeX engine (heavy) and bypasses the DOCX. Rejected.

### D5: Converter backend interface (swappable)
**Choice**: A `PdfConverter` protocol with `convert(docx_path, out_path=None) -> Path`. Implementations: `LibreOfficeConverter` (default), `Docx2PdfConverter` (lazy-imported, optional). `get_converter(backend=None)` resolves the backend from the `DOCS_PDF_BACKEND` env var (default `libreoffice`). `docx_to_pdf(...)` is the public facade.
**Rationale**: Decouples the public API from the conversion mechanism; lets dev/container differ without code changes; makes the LibreOffice dependency injectable/mockable for tests (converter tests run against a fake backend plus one real-conversion smoke test gated on `soffice` availability).

### D6: Module structure
**Choice**: `src/docs/` package:
- `slots.py` - `SLOT_PATTERN`, `slot_token`, `find_slots`, `fill_slots`, `SlotValueError`.
- `generator.py` - Markdown renderer + `create_docx`, `add_slot`.
- `converter.py` - `PdfConverter` protocol, `LibreOfficeConverter`, `Docx2PdfConverter`, `get_converter`, `docx_to_pdf`, `ConverterNotAvailableError`.
- `__init__.py` - re-exports the public API.
**Rationale**: Separates the three concerns (slots, docx building, pdf conversion) for independent testing and clear ownership.

## Risks / Trade-offs

- **[Slot token spans multiple runs in externally-authored DOCX]** -> For documents we generate, each slot is a single run (D2), so `fill_slots` is format-safe. For externally-authored DOCX where a token may be split across runs, `fill_slots` rebuilds the paragraph's runs from concatenated text, which can flatten intra-paragraph formatting on that paragraph. Documented in the docstring; acceptable since the primary flow is our own generated docs.
- **[LibreOffice not installed]** -> `LibreOfficeConverter.convert` raises `ConverterNotAvailableError` with install guidance. `Dockerfile` adds the `libreoffice` layer; dev macOS requires `brew install --cask libreoffice`. The `docx_to_pdf` smoke test is skipped when `soffice` is absent.
- **[Subprocess cold-start overhead]** -> Each conversion spawns `soffice` (~1-3s). Acceptable for low/medium volume (the stated use case). High-throughput pooling is a non-goal.
- **[Concurrent `soffice` profile locks]** -> Mitigated by a per-process `UserInstallation` dir (D4); still, parallel conversions to the same output path would collide - callers must use distinct output paths.
- **[Limited Markdown fidelity]** -> Tables/code/images render as plain paragraphs. Documented; out of scope.
- **[`{{ }}` collision with literal text]** -> Negligible in Chinese legal contracts; documented as the reserved token syntax.

## Migration Plan

1. Add `python-docx>=1.1` to `pyproject.toml` deps; `uv sync`.
2. Add the `libreoffice` system package to `Dockerfile`; rebuild image.
3. Land `src/docs/` module + tests.
4. No data or runtime migration - nothing consumes the module yet, so deployment is zero-impact.
5. **Rollback**: remove `src/docs/`, revert `pyproject.toml` and `Dockerfile`. No runtime behavior changes since no consumer exists.

## Open Questions

- **Slot placeholder visual style**: default to yellow highlight + `{{name}}` text (decision in D2); revisit if users prefer underline/blanks. Resolvable during implementation without changing the API.
- **`create_docx` content source**: accept a generic Markdown string now (works with existing `output/*.md` and `templates/*.md`); a dedicated template-loader helper is a follow-up if the pipeline needs it.
