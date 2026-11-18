## 1. Setup

- [x] 1.1 Add `python-docx>=1.1` to `pyproject.toml` `[project].dependencies` and run `uv sync` to update `uv.lock`
- [x] 1.2 Add the `libreoffice` system package to `Dockerfile` (headless PDF conversion backend for the container image)
- [x] 1.3 Create the `src/docs/` package directory with an empty `__init__.py` placeholder

## 2. Slot model (`src/docs/slots.py`)

- [x] 2.1 Define `SLOT_PATTERN` regex (`\{\{\s*([a-zA-Z_][\w-]*)\s*\}`) and `slot_token(name) -> str` returning `"{{name}}"`
- [x] 2.2 Implement `find_slots(doc)` accepting a path or open `Document`, returning de-duplicated slot names in first-appearance order
- [x] 2.3 Implement the paragraph-level replacement helper that substitutes `{{slot}}` tokens with values, handling tokens split across runs by rebuilding paragraph runs from concatenated text
- [x] 2.4 Implement `fill_slots(doc, values, *, strict=False) -> int` (lenient default leaves unfilled tokens; `strict=True` raises `SlotValueError` listing missing names; multi-line values insert line breaks) and define `SlotValueError`

## 3. DOCX generator (`src/docs/generator.py`)

- [x] 3.1 Implement the lightweight Markdown-to-DOCX renderer: `#`/`##`/`###` -> Heading 1/2/3, `**bold**`/`*italic*` -> styled runs, `- `/`* ` -> bullet list, `1. ` -> numbered list, `---` -> horizontal rule, blank-line-separated text -> paragraphs
- [x] 3.2 Implement `create_docx(content, output_path, *, slots=None, title=None) -> Path`: render content, apply slot values (replace token with value where `slots[name]` is non-None, else write the token as a single yellow-highlighted run), create parent dirs, save, return path
- [x] 3.3 Implement `add_slot(doc, slot_name, *, label=None, value=None) -> None` accepting a path or open `Document`: append a paragraph `{{slot_name}}` (or `label: {{slot_name}}`), highlighted, or pre-filled when `value` is given

## 4. PDF converter (`src/docs/converter.py`)

- [x] 4.1 Define the `PdfConverter` protocol (`convert(docx_path, out_path=None) -> Path`) and `ConverterNotAvailableError`
- [x] 4.2 Implement `LibreOfficeConverter` invoking `soffice --headless --convert-to pdf --outdir <dir>` with a per-process `-env:UserInstallation=file:///tmp/lo-profile-...`, raising `ConverterNotAvailableError` when `soffice` is missing
- [x] 4.3 Implement `Docx2PdfConverter` with a lazy `docx2pdf` import (so it stays optional) delegating to `docx2pdf.convert`
- [x] 4.4 Implement `get_converter(backend=None)` resolving from arg -> `DOCS_PDF_BACKEND` env -> `libreoffice` (default), raising `ValueError` for unknown backends
- [x] 4.5 Implement `docx_to_pdf(docx_path, *, output_path=None, backend=None) -> Path` facade: resolve backend, default output path = source with `.pdf`, return the PDF path

## 5. Public API (`src/docs/__init__.py`)

- [x] 5.1 Re-export the public API: `create_docx`, `add_slot`, `fill_slots`, `find_slots`, `slot_token`, `docx_to_pdf`, `create_pdf`, `get_converter`, `SlotValueError`, `ConverterNotAvailableError`
- [x] 5.2 Implement `create_pdf(content, output_path, *, slots=None, title=None, backend=None) -> Path` convenience wrapper (build DOCX via `create_docx` to a sibling `.docx`, then `docx_to_pdf`, return PDF path)

## 6. Tests

- [x] 6.1 `tests/test_docs_slots.py`: `slot_token`, `find_slots` (incl. dedup/order), `fill_slots` (fill, partial fill, strict raises `SlotValueError`, multi-line)
- [x] 6.2 `tests/test_docs_generator.py`: `create_docx` produces valid docx with headings/lists/paragraphs, creates parent dirs, applies `title`, fills slots from `slots`, leaves highlighted `{{name}}` placeholders when absent or `None`; `add_slot` labeled/unlabeled/pre-filled
- [x] 6.3 `tests/test_docs_converter.py`: `get_converter` default/env/unknown-backend behavior; `docx_to_pdf` output-path resolution; one real-conversion smoke test (skipped via `pytest.skip` when `soffice` is absent); `ConverterNotAvailableError` path using a fake/missing binary
- [x] 6.4 Run `uv run pytest tests/test_docs_*.py` and confirm all tests pass

## 7. Verification

- [x] 7.1 Run `uv run python -c "from src.docs import create_docx, add_slot, fill_slots, find_slots, slot_token, docx_to_pdf, create_pdf, get_converter; print('imports ok')"` to confirm the public API imports cleanly
- [x] 7.2 Run `uv run python -c "from src.docs import create_docx, find_slots, fill_slots; p=create_docx('# 服务协议\n\n甲方：{{party_a}}\n乙方：{{party_b}}', 'output/sample.docx', slots={'party_a':'北京甲公司'}); print(p, find_slots(p)); print(fill_slots(p, {'party_b':'北京乙公司'}))"` and verify `party_a` is pre-filled, `party_b` filled afterward, and no tokens remain
- [x] 7.3 Run `openspec validate add-docx-pdf-generation-slots` and confirm the change is valid
