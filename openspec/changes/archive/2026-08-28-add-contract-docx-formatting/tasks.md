# Tasks: Contract DOCX Formatting

## 1. Style helper — `src/generator/generator.py`

- [x] 1.1 Add module constants `_BODY_FONT = "宋体"`, `_HEADING_FONT = "黑体"` (with a `ponytail:` comment noting the container-font caveat) and sizes for Normal/H1/H2/H3.
- [x] 1.2 Add `_set_eastasia_font(run_or_style, name)` — sets both Latin (`w:rFonts/@w:ascii`+`@w:hAnsi`) and CJK (`w:rFonts/@w:eastAsia`) so Chinese actually changes face.
- [x] 1.3 Add `_apply_zh_document_style(document)` — A4 section + margins, `Normal` font/size/2-char indent/line spacing, restyle `Heading 1/2/3` (黑体, black, sized, H1 centered).
- [x] 1.4 Call `_apply_zh_document_style(document)` immediately after `Document()` in `create_docx`.

## 2. Highlight toggle

- [x] 2.1 Add `highlight_slots: bool = True` to `create_docx` signature.
- [x] 2.2 Thread the flag through `_render_markdown` → `_render_inline`; skip `run.font.highlight_color = WD_COLOR_INDEX.YELLOW` when `False` (literal `{{slot}}` text still emitted).

## 3. Signature block

- [x] 3.1 Add `_render_signature_block(document, lines)` — two-column, borderless, right-aligned table for the trailing signature lines.
- [x] 3.2 In `_render_markdown`, detect the `## 签署信息` heading (and the static `（签字/盖章）` marker pairs); route the following lines to `_render_signature_block` instead of plain paragraphs.

## 4. Tests — `tests/test_docs_formatting.py` (new)

- [x] 4.1 Font: generated DOCX `Normal` style has `eastAsia == 宋体` (inspect `rPr.rFonts`), not just Latin.
- [x] 4.2 Page: `section.page_width == Mm(210)` (A4), margins set.
- [x] 4.3 Indent: `Normal` paragraph has `w:ind/@w:firstLineChars == 200`.
- [x] 4.4 Heading: `Heading 1` is 黑体 + black + centered.
- [x] 4.5 Highlight off: `create_docx(..., highlight_slots=False)` → unfilled slot run has no `w:highlight`; `find_slots` still returns it.
- [x] 4.6 Highlight on (default): unfilled slot run still has yellow highlight (regression guard).
- [x] 4.7 Signature: body ending in `## 签署信息` produces a 2-col table, not plain paragraphs.

## 5. Regression + verify

- [x] 5.1 Run `uv run pytest tests/test_docs_generator.py tests/test_docs_slots.py tests/test_docs_formatting.py -q` — all pass.
- [x] 5.2 Run full suite `uv run pytest -q`; confirm no new failures beyond the pre-existing generator-rules debt.

## 6. Deployment follow-up (post-merge)

- [x] 6.1 Confirm the container has a CJK font (宋体/黑体 or Noto CJK) for PDF rendering; if not, install one in the image. — added `fonts-noto-cjk` to the `Dockerfile` apt install line; LibreOffice now substitutes 宋体/黑体 with Noto CJK for PDF.
- [x] 6.2 Re-run `generate_all_stored` (or equivalent) to regenerate the 724 artifacts with the new formatting — content-hash doesn't change, so this must be forced. — added `force: bool` to `generate_stored` / `generate_all_stored` + `--force` to `scripts/generate_all_types_stored.py` + `force` on the `generate-stored` API; run `PYTHONPATH=. python3 scripts/generate_all_types_stored.py --force` (or POST `{"force": true}` per type) against the live cluster at deploy time.
