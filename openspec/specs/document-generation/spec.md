# document-generation Specification

## Purpose
Generate DOCX and PDF documents from Markdown with a slot-token model that is injected at generation time and convertible from DOCX to PDF.

## Requirements
### Requirement: DOCX Generation from Markdown Content
The system SHALL provide a `create_docx(content, output_path, *, slots=None, title=None)` function that renders Markdown contract content into a formatted `.docx` file at `output_path` and returns the resolved path. The renderer SHALL map `#`/`##`/`###` to headings, `**bold**` and `*italic*` to styled runs, `- `/`* ` to bullet lists, `1. ` to numbered lists, `---` to a horizontal rule, and blank-line-separated text to paragraphs. The function SHALL create parent directories that do not exist.

#### Scenario: Generate a DOCX from Markdown content
- **WHEN** `create_docx("# 服务协议\n\n甲方与乙方就服务事宜达成如下协议。\n\n## 第一条 服务内容\n\n- 甲方提供咨询\n- 乙方支付费用", "output/contract.docx")` is called
- **THEN** a valid `.docx` file exists at `output/contract.docx`
- **THEN** the returned path equals `output/contract.docx`
- **THEN** the document contains a Heading 1 "服务协议", a Heading 2 "第一条 服务内容", a normal paragraph for the preamble, and two bullet-list items

#### Scenario: Missing parent directory is created
- **WHEN** `create_docx("# Title", "output/nested/deep/contract.docx")` is called and `output/nested/deep/` does not exist
- **THEN** the directory is created and the `.docx` file is written successfully

#### Scenario: Optional title becomes the first heading
- **WHEN** `create_docx("正文内容", "output/c.docx", title="合同标题")` is called
- **THEN** the document's first paragraph is a Heading 1 containing "合同标题" followed by the body content

### Requirement: Slot Token Model
The system SHALL represent a slot as a `{{slot_name}}` token where `slot_name` matches `[a-zA-Z_][\w-]*`. The system SHALL expose `slot_token(name)` returning `"{{name}}"` and `find_slots(doc)` returning the de-duplicated list of slot names present in a document (accepting a path or an open `Document`).

#### Scenario: Build and discover a slot token
- **WHEN** `slot_token("party_a")` is called
- **THEN** it returns the string `"{{party_a}}"`

#### Scenario: Discover slots in a generated document
- **WHEN** `create_docx("甲方：{{party_a}}\n乙方：{{party_b}}\n日期：{{party_a}}", "output/c.docx")` is called and then `find_slots("output/c.docx")` is called
- **THEN** the returned list equals `["party_a", "party_b"]` (order preserved by first appearance, duplicates removed)

### Requirement: Slot Injection at Generation Time
`create_docx` SHALL accept an optional `slots: dict[str, str | None]` mapping. For each `{{slot_name}}` token in the content: if `slots` contains a non-None value for that name, the token SHALL be replaced with that value in the generated DOCX; if `slots` is absent or maps the name to `None`, the token SHALL be rendered as a visible, highlighted placeholder run containing the literal `{{slot_name}}` text.

#### Scenario: Slots filled at generation time
- **WHEN** `create_docx("甲方：{{party_a}}", "output/c.docx", slots={"party_a": "北京甲公司"})` is called
- **THEN** the generated document's text contains "甲方：北京甲公司" and contains no `{{party_a}}` placeholder

#### Scenario: Unfilled slots remain as highlighted placeholders
- **WHEN** `create_docx("甲方：{{party_a}}", "output/c.docx")` is called with no `slots`
- **THEN** the generated document contains the text `{{party_a}}` rendered in a run with yellow highlight

#### Scenario: Explicit None leaves the placeholder
- **WHEN** `create_docx("甲方：{{party_a}}", "output/c.docx", slots={"party_a": None})` is called
- **THEN** the generated document still contains the highlighted `{{party_a}}` placeholder

### Requirement: Slot Filling
The system SHALL provide `fill_slots(doc, values, *, strict=False)` that replaces `{{slot_name}}` tokens in an existing DOCX with values from `values: dict[str, str]`, accepting a path or an open `Document`. It SHALL return the number of tokens replaced. By default, tokens without a provided value SHALL be left untouched; when `strict=True`, any slot present in the document but missing from `values` SHALL raise `SlotValueError` listing the missing slot names. Multi-line string values SHALL insert line breaks.

#### Scenario: Fill slots in an existing document
- **WHEN** a DOCX containing "甲方：{{party_a}}" is generated and `fill_slots(doc_path, {"party_a": "北京甲公司"})` is called
- **THEN** the document text becomes "甲方：北京甲公司"
- **THEN** the returned count is `1`

#### Scenario: Partial fill leaves unfilled tokens in place
- **WHEN** a DOCX containing `{{party_a}}` and `{{party_b}}` is generated and `fill_slots(doc_path, {"party_a": "甲"})` is called with `strict=False` (default)
- **THEN** `{{party_a}}` is replaced with "甲", `{{party_b}}` remains unchanged, and the returned count is `1`

#### Scenario: Strict mode raises on missing values
- **WHEN** a DOCX containing `{{party_a}}` and `{{party_b}}` is generated and `fill_slots(doc_path, {"party_a": "甲"}, strict=True)` is called
- **THEN** `SlotValueError` is raised and its message names `party_b` as missing

### Requirement: Adding a Slot to an Existing Document
The system SHALL provide `add_slot(doc, slot_name, *, label=None, value=None)` that inserts a slot into an existing DOCX (accepting a path or an open `Document`). When `label` is provided, the inserted paragraph SHALL read `label: {{slot_name}}`; otherwise it SHALL read `{{slot_name}}`. The slot token SHALL be rendered as a highlighted placeholder. When `value` is provided, the slot SHALL be immediately filled with that value instead of left as a placeholder.

#### Scenario: Add a labeled placeholder slot
- **WHEN** `add_slot(doc_path, "sign_date", label="签署日期")` is called on an existing document
- **THEN** a new paragraph is appended containing "签署日期: {{sign_date}}" with the token highlighted
- **THEN** `find_slots(doc_path)` subsequently includes `"sign_date"`

#### Scenario: Add a slot pre-filled with a value
- **WHEN** `add_slot(doc_path, "amount", label="金额", value="人民币壹万元整")` is called
- **THEN** the appended paragraph contains "金额: 人民币壹万元整" and contains no `{{amount}}` placeholder

### Requirement: DOCX to PDF Conversion
The system SHALL provide `docx_to_pdf(docx_path, *, output_path=None, backend=None)` that converts a `.docx` file to a `.pdf` file and returns the resolved PDF path. When `output_path` is `None`, the PDF SHALL be written next to the source with a `.pdf` extension. The default conversion backend SHALL be headless LibreOffice. If the selected backend's required system binary is not available, the system SHALL raise `ConverterNotAvailableError` with install guidance.

#### Scenario: Convert a DOCX to PDF with default output path
- **WHEN** `docx_to_pdf("output/contract.docx")` is called and the LibreOffice backend is available
- **THEN** a file `output/contract.pdf` is created
- **THEN** the returned path equals `output/contract.pdf`

#### Scenario: Convert with an explicit output path
- **WHEN** `docx_to_pdf("output/contract.docx", output_path="output/final.pdf")` is called and the backend is available
- **THEN** the PDF is written to `output/final.pdf` and that path is returned

#### Scenario: Backend unavailable raises a clear error
- **WHEN** `docx_to_pdf("output/contract.docx")` is called and the `soffice` binary cannot be found
- **THEN** `ConverterNotAvailableError` is raised with a message instructing how to install LibreOffice

### Requirement: PDF Convenience Generation
The system SHALL provide `create_pdf(content, output_path, *, slots=None, title=None, backend=None)` that generates a DOCX from the content (via `create_docx`) and then converts it to PDF (via `docx_to_pdf`), writing the PDF to `output_path` and returning the PDF path. The intermediate DOCX SHALL be written alongside the PDF with a `.docx` extension unless the caller removes it.

#### Scenario: Generate a PDF directly from Markdown
- **WHEN** `create_pdf("# 服务协议\n\n甲方：{{party_a}}", "output/contract.pdf", slots={"party_a": "北京甲公司"})` is called and a PDF backend is available
- **THEN** `output/contract.pdf` exists and is a non-empty PDF file
- **THEN** an intermediate `output/contract.docx` also exists
- **THEN** the returned path equals `output/contract.pdf`

### Requirement: Converter Backend Selection
The system SHALL resolve the PDF conversion backend from the `backend` argument, falling back to the `DOCS_PDF_BACKEND` environment variable, falling back to `libreoffice` when unset. The system SHALL expose `get_converter(backend=None)` returning a converter implementing the `PdfConverter` protocol (`convert(docx_path, out_path=None) -> Path`). A `docx2pdf` backend SHALL be selectable and its dependency imported lazily so it is optional. An `http` backend SHALL be selectable that delegates conversion to a render service: its endpoint SHALL be read from the `RENDER_SERVICE_URL` environment variable, no network call SHALL happen at converter construction, and `convert` SHALL return a local PDF path after downloading the service's response to the requested output path. When the `http` backend is selected and `RENDER_SERVICE_URL` is unset, or the render service is unreachable or returns a non-success response, `convert` SHALL raise `ConverterNotAvailableError` with guidance naming the missing configuration or the failing endpoint.

#### Scenario: Default backend is LibreOffice
- **WHEN** `get_converter()` is called with no argument and `DOCS_PDF_BACKEND` is unset
- **THEN** a `LibreOfficeConverter` instance is returned

#### Scenario: Backend selected via environment variable
- **WHEN** `DOCS_PDF_BACKEND=docx2pdf` is set in the environment and `get_converter()` is called
- **THEN** a `Docx2PdfConverter` instance is returned (without importing `docx2pdf` until `convert` is called)

#### Scenario: Unknown backend raises an error
- **WHEN** `get_converter("weasyprint")` is called
- **THEN** a `ValueError` is raised naming the unsupported backend

#### Scenario: HTTP backend selected via environment variables
- **WHEN** `DOCS_PDF_BACKEND=http` and `RENDER_SERVICE_URL=http://render-service.law-bench.svc.cluster.local:8090` are set and `get_converter()` is called
- **THEN** an HTTP render-service converter instance is returned without any network request being made

#### Scenario: HTTP backend without a service URL fails clearly
- **WHEN** `DOCS_PDF_BACKEND=http` is set, `RENDER_SERVICE_URL` is unset, and `docx_to_pdf` is called
- **THEN** `ConverterNotAvailableError` is raised with a message naming the `RENDER_SERVICE_URL` variable to set

#### Scenario: HTTP backend surfaces an unreachable service
- **WHEN** the HTTP backend converts a DOCX and the render service at `RENDER_SERVICE_URL` is unreachable or responds with a non-success status
- **THEN** `ConverterNotAvailableError` is raised with a message naming the failing endpoint


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
