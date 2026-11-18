# Proposal: Contract DOCX Formatting

## Why

Generated contract deliverables (DOCX + PDF) look like drafts, not finished legal documents. Every generation path — the simple template renderer (`src/contracts/generator.py`) and the tag-driven assembler (`src/clauses/assemble.py`) — converges on one function, `create_docx(body, path, title=zh)` in `src/generator/generator.py:124`, which renders onto python-docx's bare default template. That template targets English documents: Calibri body, blue Calibri Light headings, Letter paper, no first-line indent, default (tight) line spacing. Chinese legal text pasted onto it looks wrong.

Five concrete defects, all stemming from that one renderer never applying Chinese document styling:

1. **中文字体不统一** — no `w:eastAsia` font is ever set, so CJK glyphs fall back to the system default.
2. **标题样式丑** — Heading 1/2/3 keep the default blue Calibri Light (left-aligned, English-sized).
3. **排版细节缺失** — Letter not A4, no 2-char first-line indent, cramped line spacing.
4. **黄色高亮槽位难看** — unfilled `{{slot}}` placeholders render with a yellow highlight, reading as a draft, not a deliverable.
5. **签署栏位置不对** — signature lines are plain body paragraphs at the end, not right-aligned/tabular.

## What Changes

- Teach `create_docx` to apply a Chinese-contract document style once at document creation: A4 page + margins, body font with `eastAsia` set, 2-char first-line indent, line spacing, and black hierarchical heading styles (黑体, centered H1, sized H2/H3).
- Add a `highlight_slots: bool = True` parameter to `create_docx` so a "成品" generation can drop the yellow placeholder highlight while a "模板" generation keeps it. Backward-compatible default.
- Render the signature block (a trailing `## 签署信息` section, or the trailing `甲方（签字/盖章）` / `乙方（签字/盖章）` line pairs in the static templates) as a right-aligned, two-column table instead of plain paragraphs.
- The two call sites (`contracts/generator.py`, `clauses/assemble.py`) keep their current `create_docx(body, str(path), title=zh)` signature — no caller changes required unless a caller wants to opt into `highlight_slots=False`.

## Capabilities

### Modified Capabilities

- `document-generation`: `create_docx` gains the new document style, the `highlight_slots` parameter, and signature-block rendering. Existing `find_slots` / `fill_slots` / `add_slot` / `docx_to_pdf` behavior is unchanged.

## Impact

- **Modified files**: `src/generator/generator.py` (the style, highlight toggle, signature rendering — all local to this module).
- **New files**: `tests/test_docs_formatting.py` (asserts fonts/eastAsia, heading style, A4, indent, highlight-off, signature table).
- **Unchanged**: the two call sites, the slot model, the content-address storage layer (`src/contracts/artifacts.py`), the MinIO corpus.
- **Dependencies**: none added (python-docx already in use; section/page and font APIs are core `python-docx`).
- **Data / re-generation**: artifacts are content-addressed by `md5(body_text)` — the *body text* does not change, so existing 724 artifacts are **not** auto-regenerated. New downloads reuse the old files until `generate_all_stored` is re-run. This is a deployment follow-up, tracked in tasks.
- **Tests**: new formatting test file; existing `test_docs_generator.py` assertions (styles list, highlight presence) must still pass — the highlight-off path is opt-in so default behavior is preserved.

## Non-goals

- No Markdown-syntax extensions (tables, underline, font-size spans) — the renderer stays a thin mapping.
- No change to `fill_slots` / `add_slot` (they already clear/fill correctly; if they need the same highlight toggle, that is a separate follow-up).
- No WYSIWYG editor or template `.docx` assets.
