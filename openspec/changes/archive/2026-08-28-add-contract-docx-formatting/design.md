# Design: Contract DOCX Formatting

## Context

`src/generator/generator.py` is the single DOCX renderer. Its `create_docx(content, output_path, *, slots=None, title=None)` builds a bare `Document()`, adds a `title` Heading 1 (if given), then walks Markdown lines via `_render_markdown` → `_render_inline`. This is where all five defects live.

```
templates/*.md        ──┐
clauses/assemble.py  ──┼──▶ create_docx(body, path, title=zh)  ──▶ DOCX ──▶ LibreOffice ──▶ PDF
contracts/generator.py ─┘        src/generator/generator.py:124
```

## The three things we add (all local to `generator.py`)

### 1. `_apply_zh_document_style(document)` — call once, after `Document()`

python-docx exposes page/paragraph/run formatting through `document.sections[0]` and style objects. Key facts that shape the implementation:

- **eastAsia font is a separate attribute.** `run.font.name = "宋体"` only sets `w:rFonts/@w:ascii`/`@w:hAnsi` (Latin). CJK glyphs read `w:rFonts/@w:eastAsia`. We must set both — via the underlying `rPr.rFonts.set(qn("w:eastAsia"), "宋体")`. Miss this and the change is a no-op.
- **Normal style governs body text.** Set `Normal`'s font (both Latin + eastAsia), size, and paragraph format (first-line indent, line spacing) once; every body paragraph inherits.
- **First-line indent must be character-based** — `w:ind/@w:firstLineChars="200"` (= 2 chars) scales with font size, unlike a fixed `@w:firstLine` twips value.
- **A4 + margins** via `section.page_width/height = Mm(210)/Mm(297)` and `section.left/right_margin = Mm(31.8)` etc. (公文-style margins).
- **Headings**: restyle `Heading 1/2/3` — 黑体, black (`RGBColor(0,0,0)`), hierarchy sizes (e.g. 二号/三号/四号 or 16/14/12pt), H1 centered, H2/H3 left. Heading font uses the same eastAsia trick.

```python
def _apply_zh_document_style(document) -> None:
    _set_section_a4(document)          # A4 + margins
    _set_font(document.styles["Normal"], _BODY_FONT, _BODY_SIZE)  # 宋体, eastAsia
    _set_indent(document.styles["Normal"])                        # firstLineChars=200 + line spacing
    _set_heading(document.styles["Heading 1"], _HEADING_FONT, size=..., center=True)
    _set_heading(document.styles["Heading 2"], _HEADING_FONT, size=..., center=False)
    _set_heading(document.styles["Heading 3"], _HEADING_FONT, size=..., center=False)
```

### 2. `highlight_slots: bool = True` on `create_docx`

`_render_inline` currently does `run.font.highlight_color = WD_COLOR_INDEX.YELLOW` for unfilled slots. Thread the flag through `_render_markdown` → `_render_inline`; when `False`, skip the highlight (the literal `{{slot}}` text still renders, so `find_slots` keeps working). Default `True` preserves all existing behavior and tests.

### 3. `_render_signature_block(...)`

The signature content arrives as either (a) a trailing `## 签署信息` section whose body is a list of `{{slot}}` lines (appended by `normalize_body`), or (b) the static templates' trailing `甲方（签字/盖章）：____` / `日期：___` line pairs. Two approaches:

- **A (chosen, minimal):** detect the signature section during the line walk — after a `## 签署信息` heading, render subsequent slot/`key：___` lines as a two-column table (`甲方（签字/盖章）` | `乙方（签字/盖章）`), right-aligned.
- B (rejected for now): a general "any `__` underline line becomes right-aligned" heuristic — too clever, false-positives on 6.1/7.1 clause text.

A signature table is one `document.add_table(rows=..., cols=2)` with cell paragraphs right-aligned and borderless. Kept deliberately simple; exact pairing (which slots pair left vs right) is derived from the section's line order.

## Open decision (flagged, not blocking)

**Font family**: 宋体/黑体 are the *declared* fonts that read correctly on the user's Windows/Word; but the PDF is produced by LibreOffice on a Linux container, which needs the actual glyphs installed (宋体/SimSun is licensed, not in stock Debian). Options:

1. Declare 宋体/黑体 in the DOCX (correct for Word on Windows) and install a CJK fallback in the container image for PDF.
2. Declare `Noto Serif CJK SC` / `Noto Sans CJK SC` (open, present in the container) — correct for container PDF, slightly "non-standard" font name if opened in Word without those fonts.

**Recommendation**: make the family a module constant (`_BODY_FONT = "宋体"`, `_HEADING_FONT = "黑体"`) with a `ponytail:` comment, and verify the container's available CJK fonts before committing. Default to 宋体/黑体 (the document *should* declare the classic legal font) and let the container install/fallback resolve PDF. Confirm during implementation.

## Where the code lives

Everything is in `src/generator/generator.py`. No imports from call sites, no new modules.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| eastAsia font not set (only Latin) → CJK unchanged | High | Explicit `w:eastAsia` set in the helper; a test asserts `rFonts@w:eastAsia == 宋体` |
| Container lacks 宋体 → PDF falls back to a different face | Medium | Confirm container fonts during impl; document the constant/override; this only affects PDF glyphs, DOCX still declares correctly |
| Style changes break existing `test_docs_generator.py` | Medium | Default `highlight_slots=True` + heading/list structure preserved; run that suite after the change |
| Signature detection misfires on non-signature trailing lines | Low | Gate on the `## 签署信息` heading (and the known static `（签字/盖章）` markers), not a blanket heuristic |
| Old 724 artifacts still serve the unformatted files | Medium | Documented re-generation step in tasks (`generate_all_stored`), not silently auto-migrated |

## Acceptance Criteria

- A generated DOCX has: A4 section, `Normal` body in 宋体 with `eastAsia` set, 2-char first-line indent, black 黑体 headings (H1 centered).
- `create_docx(..., highlight_slots=False)` renders unfilled `{{slot}}` text with no yellow highlight; `find_slots` still finds them.
- A body ending in a `## 签署信息` section renders its slot lines as a right-aligned two-column signature table.
- `create_docx(..., highlight_slots=True)` (default) is byte-for-byte behaviorally unchanged for the existing cases.
- Existing `test_docs_generator.py` + `test_docs_slots.py` pass; new `test_docs_formatting.py` covers the above.
