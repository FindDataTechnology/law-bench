# render-service Specification

## Purpose

A shared in-cluster document-rendering service: a small HTTP wrapper around
headless LibreOffice that converts DOCX uploads to PDF, so application images
(web, review backend, MCP) can ship without LibreOffice and still produce
CJK-correct PDFs.

## Requirements

### Requirement: Convert DOCX to PDF over HTTP

The service SHALL accept an unauthenticated `POST /convert`
request carrying a `.docx` file as a multipart form field, and SHALL respond
with the rendered PDF bytes (`application/pdf`). The input file SHALL NOT be
retained after the response is sent.

#### Scenario: Convert an uploaded contract DOCX

- **WHEN** a client POSTs a valid contract `.docx` to `/convert` as a
  multipart file field
- **THEN** the response status is 200 with content type `application/pdf`
  and the body is a non-empty PDF whose page count matches the DOCX content

#### Scenario: Rendered PDF matches the local LibreOffice output channel

- **WHEN** the same DOCX is converted via the service and via the
  application's built-in LibreOffice backend
- **THEN** both outputs are non-empty PDFs containing the same document text

### Requirement: Health endpoint

The service SHALL expose `GET /health` returning HTTP 200 with a short JSON
body once the pod is ready to serve conversions.

#### Scenario: Liveness probe passes when ready

- **WHEN** `GET /health` is called on a started service pod
- **THEN** the response is 200 with a JSON body identifying the service

### Requirement: CJK rendering fidelity

The service SHALL render Chinese text in converted PDFs using an installed
CJK font (Noto CJK), substituting for proprietary 宋体/黑体 faces declared by
the DOCX, so Chinese characters never render as placeholder boxes.

#### Scenario: Chinese contract renders without tofu

- **WHEN** a DOCX whose body text is Chinese and declares 宋体 (SimSun) is
  converted
- **THEN** the produced PDF contains the original Chinese text and embeds a
  CJK font, with no placeholder-box glyphs

### Requirement: Invalid input and conversion failure handling

The service SHALL reject a request whose multipart body is missing the file
field or whose upload is not a DOCX, with HTTP 400; an upload exceeding the
configured size limit SHALL be rejected with HTTP 413. If the underlying
LibreOffice conversion fails, the service SHALL respond with HTTP 500 and a
JSON error body naming the failure.

#### Scenario: Missing or wrong-type upload is rejected

- **WHEN** `/convert` receives a request without a file field or with a
  non-DOCX file
- **THEN** the response is 400 with a JSON error body

#### Scenario: Oversized upload is rejected

- **WHEN** `/convert` receives an upload larger than the configured limit
- **THEN** the response is 413

#### Scenario: Conversion failure surfaces as a 500

- **WHEN** LibreOffice exits non-zero on an uploaded file
- **THEN** the response is 500 with a JSON error body and the service keeps
  serving subsequent requests

### Requirement: Concurrent conversions are isolated

The service SHALL perform each conversion in its own temporary workspace and
LibreOffice profile, such that concurrent requests never share lock or
output files and each response returns its own correct PDF.

#### Scenario: Two simultaneous conversions do not interfere

- **WHEN** two clients POST different DOCX files to `/convert` at the same
  time
- **THEN** both responses are 200 and each PDF contains the text of its own
  source document
