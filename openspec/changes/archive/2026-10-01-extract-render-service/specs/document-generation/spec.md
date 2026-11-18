## MODIFIED Requirements

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
