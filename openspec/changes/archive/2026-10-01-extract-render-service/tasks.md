# Tasks: extract-render-service

## 1. HTTP backend (converter seam)

- [x] 1.1 Add `HttpRenderConverter` to `src/generator/converter.py`: name `http`, reads `RENDER_SERVICE_URL` at convert time, multipart upload via httpx, streams response to `out_path` (default `<stem>.pdf`), 120 s timeout; unset URL / connect error / non-2xx → `ConverterNotAvailableError` naming the env var or endpoint; register in `_BACKENDS`
- [x] 1.2 Export `HttpRenderConverter` from `src/generator/__init__.py`
- [x] 1.3 Tests in `tests/test_docs_converter.py`: backend resolved from `DOCS_PDF_BACKEND=http`; construction makes no network call; unset `RENDER_SERVICE_URL` raises `ConverterNotAvailableError`; successful convert via httpx mock transport writes the PDF and returns the path; non-2xx raises `ConverterNotAvailableError`

## 2. Render service app

- [x] 2.1 Create `src/render_service/app.py`: FastAPI app with `POST /convert` (multipart field `file`, DOCX check → 400, `RENDER_MAX_UPLOAD_MB` default 50 → 413, per-request temp workspace + LO profile, subprocess `soffice --headless`, 200 `application/pdf` or 500 JSON) and `GET /health`; run conversion off the event loop (`asyncio.to_thread` / threadpool)
- [x] 2.2 Tests for the service app: convert round-trip (needs local soffice; skip-if-missing marker consistent with existing converter tests), health, 400 on missing/non-DOCX field, 413 on oversize, 500 on conversion failure, concurrent conversions isolated
- [x] 2.3 Verify CJK fidelity locally: convert a 宋体-declaring Chinese contract DOCX through the service; PDF text extractable, no tofu (extend or add test using the existing document-generation fixtures)

## 3. Images & CI

- [x] 3.1 Add `Dockerfile.render`: `python:3.12-slim`, apt `libreoffice-writer fonts-noto-cjk` (with the DEBIAN_MIRROR args + Acquire timeouts carried over for the Jenkins fallback path), `pip install` pinned `fastapi uvicorn python-multipart`, non-root user, `uvicorn` on 0.0.0.0:8090, copy `src/render_service/` only
- [x] 3.2 CI image workflow (superseded 2026-10-01: onboarded onto the tcr-image-pipeline standard channel instead of extending build-and-push.yml) — `image.yml` matrix builds `law-template` + `law-render`, pushes `hkccr.ccs.tencentyun.com` (secrets TCR_USERNAME/TCR_PASSWORD, `sha-<short>` + `main`, provenance false); cheap-3 relay repos.conf lists `law-bench/law-render`; obsolete workflows deleted
- [x] 3.3 Slim root `Dockerfile`: remove the `libreoffice-writer fonts-noto-cjk` apt layer (and its now-unused mirror ARGs if nothing else uses them); note the ~GB delta in the image-size check
- [x] 3.4 Slim `Dockerfile.review-backend`: remove its `libreoffice-writer` install (keep libpq-dev/gcc — still needed for psycopg build)

## 4. Deploy manifests

- [x] 4.1 Add `deploy/render-service-deployment.yaml`: ns `law-bench`, 1 replica, no node pin, no PVC, image `ccr.ccs.tencentyun.com/law-bench/law-render:sha-<x>`, `imagePullSecrets: tcr-pull`, readiness+liveness `GET /health`, modest requests/limits (256Mi/500m)
- [x] 4.2 Add `deploy/render-service-service.yaml`: ClusterIP `render-service` port 8090
- [x] 4.3 Add `DOCS_PDF_BACKEND=http` + `RENDER_SERVICE_URL=http://render-service.law-bench.svc.cluster.local:8090` to the web container in `deploy/deployment.yaml` and the assistant-MCP container in `deploy/assistant-mcp-deployment.yaml`
- [x] 4.4 Same env pair for the review-agent backend in `deploy/review-agent/backend-deployment.yaml`

## 5. Verification & rollout

- [x] 5.1 Local: full converter + service test suites pass (`DOCS_PDF_BACKEND` unset default path unchanged — run existing `tests/test_docs_converter.py`, `tests/test_clauses_assemble.py`, contract artifact tests)
- [x] 5.2 Push to GitHub; verify the image workflow publishes BOTH `law-template:sha-<x>` and `law-render:sha-<x>` to hkccr, and the relay backfills them to ccr within one 5-min cycle
- [x] 5.3 Deploy render service first (manifest to Gitee): pod Running/Ready, `/health` 200 from inside the cluster, manual `/convert` round-trip from the web pod
- [x] 5.4 Env switch roll (web + assistant-MCP on fat image): rolled 507ff23; web /healthz 200, render-service healthy, assistant-MCP serving (401 fail-closed). End-to-end VERIFIED from inside the web pod via cheap6 kubectl (ssh-mcp-server creds): production env shows backend=http, docx_to_pdf produced a 30,925-byte %PDF-1.7 through render-service
- [x] 5.5 Slim-image roll (af86aee → sha-ba0a6c9): web/seed-db/assistant-MCP healthy post-roll. Measured on cheap-7 containerd: fat 1.95 GB vs slim 477 MB = 1.47 GB saved per image (registry-side: slim 454.5 MB compressed, venv layer 363 MB pushes fine via hk leg; law-render 271.8 MB = LO 149.8 + fonts 72.7 MB split layers)
- [x] 5.6 Rollback rehearsal (verified): image axis — revert to the Harbor-ref fat tag sha-db5ed10 (confirmed present node-local on cheap-7, 1.95 GB; sha-98bbbb8 itself was already GC'd) ; render-path axis — DOCS_PDF_BACKEND=libreoffice on any fat tag (local soffice). Neither needs a rebuild
