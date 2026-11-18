# document-generation Delta Spec

## ADDED Requirements

### Requirement: Chinese Contract Document Style
`create_docx` SHALL apply a Chinese-contract document style to the document it produces: an A4 page with non-default margins, a body (`Normal`) style using a serif CJK font whose `w:eastAsia` attribute is set (not merely the Latin face), a 2-character first-line indent expressed as `w:firstLineChars="200"`, and line spacing greater than the default. The `Heading 1`/`Heading 2`/`Heading 3` styles SHALL be restyled to a black sans-serif CJK font with hierarchical sizes, `Heading 1` centered.

#### Scenario: Generated document is A4
- **WHEN** `create_docx("正文", "out.docx")` is called
- **THEN** the document's first section has `page_width == Mm(210)` and `page_height == Mm(297)`

#### Scenario: Body font sets the CJK face
- **WHEN** `create_docx("正文", "out.docx")` is called
- **THEN** the `Normal` style's run font has an `w:rFonts` element whose `w:eastAsia` attribute is set (to the configured CJK serif font)

#### Scenario: Body paragraph uses a 2-character first-line indent
- **WHEN** `create_docx("正文", "out.docx")` is called
- **THEN** the body paragraph's `w:ind` carries `w:firstLineChars="200"`

#### Scenario: Heading 1 is a centered black CJK heading
- **WHEN** `create_docx("# 标题", "out.docx")` is called
- **THEN** the `Heading 1` paragraph's run font is black and its `w:eastAsia` is set to the configured CJK sans-serif font, and the paragraph is centered

### Requirement: Slot Highlight Toggle
`create_docx` SHALL accept a `highlight_slots: bool = True` parameter. When `highlight_slots` is `True` (the default), unfilled `{{slot}}` tokens SHALL be rendered as highlighted placeholder runs (existing behavior). When `highlight_slots` is `False`, unfilled `{{slot}}` tokens SHALL be rendered as literal `{{slot}}` text with no highlight, and `find_slots` SHALL still discover them.

#### Scenario: Highlight disabled removes the highlight but keeps the token
- **WHEN** `create_docx("甲方：{{party_a}}", "out.docx", highlight_slots=False)` is called
- **THEN** the generated document contains the text `{{party_a}}` in a run with no `w:highlight`
- **THEN** `find_slots("out.docx")` returns `["party_a"]`

#### Scenario: Default still highlights placeholders
- **WHEN** `create_docx("甲方：{{party_a}}", "out.docx")` is called (no `highlight_slots`)
- **THEN** the `{{party_a}}` placeholder run carries a highlight

### Requirement: Signature Block Rendering
`create_docx` SHALL render a trailing signature section — a `## 签署信息` heading followed by slot/blank lines — as a borderless two-column table with right-aligned cell text, rather than as plain body paragraphs.

#### Scenario: Signature section becomes a table
- **WHEN** `create_docx("## 签署信息\n\n{{party_a_sign}}\n\n{{party_b_sign}}", "out.docx")` is called
- **THEN** the document contains a table with two columns (not two plain paragraphs) for the signature lines
