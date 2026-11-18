# Proposal: extract-render-service

## Why

The web image (`law-template`, shared by the web, seed-db, and assistant-MCP
pods) carries headless LibreOffice + Noto CJK fonts solely for DOCX→PDF
conversion, adding roughly 1.2–1.5 GB to every copy of the image — and
`Dockerfile.review-backend` installs LibreOffice again for the same purpose.
Since the TCR image pipeline landed (2026-09-30), every code push ships this
dead weight across the Pacific twice over (build upload + cluster pull on
every roll). `src/generator/converter.py` already defines the
`PdfConverter` protocol with a pluggable backend registry
(`get_converter` / `DOCS_PDF_BACKEND`), so moving rendering out of the app
image into one shared pod is a seam that is already paid for.

## What Changes

- New in-repo **render service**: a minimal HTTP wrapper around headless
  LibreOffice (`POST /convert` DOCX→PDF, `GET /health`), served by its own
  slim image `Dockerfile.render` (python-slim + libreoffice-writer +
  fonts-noto-cjk + fastapi/uvicorn only), deployed as its own pod + Service
  in namespace `law-bench`.
- New **`http` PDF backend** in `src/generator/converter.py`, selected via
  `DOCS_PDF_BACKEND=http` + `RENDER_SERVICE_URL`; uses httpx (already in the
  lockfile) so no new client dependency. All existing callers
  (`src/clauses/assemble.py`, `src/contracts/generator.py`,
  `src/contracts/artifacts.py`, the MCP generate tool) keep calling
  `docx_to_pdf` unchanged.
- **Web image slimming**: drop the `libreoffice-writer fonts-noto-cjk` apt
  layer from the root `Dockerfile` (~1.2–1.5 GB smaller image).
- **review-backend slimming**: drop LibreOffice from
  `Dockerfile.review-backend` and point the review-agent backend at the same
  shared service (second consumer, proving the sharing claim).
- **CI**: `.github/workflows/build-and-push.yml` builds and pushes a second
  image `ccr.ccs.tencentyun.com/law-bench/law-render` on the same triggers
  with the same `sha-<short>` tag scheme.
- **Deploy**: new `deploy/render-service-deployment.yaml` (+ Service);
  `DOCS_PDF_BACKEND=http` + `RENDER_SERVICE_URL` env added to the web and
  assistant-MCP deployments.
- Default backend stays `libreoffice`, so local/dev workflows without the
  service are unaffected.

## Capabilities

### New Capabilities
- `render-service`: HTTP document-rendering service — accepts a DOCX upload,
  returns a PDF rendered with correct CJK fonts, isolated per request,
  shareable by multiple in-cluster apps.

### Modified Capabilities
- `document-generation`: "Converter Backend Selection" requirement gains the
  `http` backend (selected via `DOCS_PDF_BACKEND` / `RENDER_SERVICE_URL`,
  raising `ConverterNotAvailableError` when the URL is unset or the service
  is unreachable).
- `image-delivery`: new requirement for building and publishing the
  `law-render` service image on the same push triggers and tag scheme as the
  main image.

## Impact

- **Code**: `src/generator/converter.py` (+~1 backend class),
  `src/generator/__init__.py` (exports), new `src/render_service/` app
  (~100 lines), tests for both.
- **Build**: root `Dockerfile` (remove apt layer), `Dockerfile.review-backend`
  (remove LibreOffice), new `Dockerfile.render`, `.github/workflows/build-and-push.yml`
  (second image target).
- **Deploy**: `deploy/deployment.yaml` + `deploy/assistant-mcp-deployment.yaml`
  (env switch), new render-service manifests; review-agent backend env.
- **Runtime topology**: PDF conversion gains a network hop; conversion
  failures now can originate from the render pod (surfaced as
  `ConverterNotAvailableError` / conversion errors — same error contract as
  today).
- **Rollback**: previous fat `sha-<x>` image tags remain in TCR; rolling back
  = repoint the manifest at the old tag (no rebuild). Deploy order matters:
  render service must be live before the slimmed web image rolls.
- **No data/schema changes; no public API changes.**
