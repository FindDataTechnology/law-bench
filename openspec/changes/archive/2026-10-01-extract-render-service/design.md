# Design: extract-render-service

## Context

See `proposal.md` — Why. Facts that shape the design:

- The seam already exists: `src/generator/converter.py` defines the
  `PdfConverter` protocol, a `_BACKENDS` registry, `get_converter()` with
  `DOCS_PDF_BACKEND` resolution, and every caller
  (`src/clauses/assemble.py`, `src/contracts/generator.py`,
  `src/contracts/artifacts.py`, MCP generate tool) goes through
  `docx_to_pdf` / `create_pdf`. No call site needs to change.
- `httpx` is already in `uv.lock` and used by `src/web`, `src/law_api`,
  `src/search` — the client backend adds no dependency.
- LibreOffice lives in two images today: root `Dockerfile`
  (`libreoffice-writer fonts-noto-cjk` apt layer, web/seed-db/assistant-MCP
  pods all run this image) and `Dockerfile.review-backend` (review-agent
  backend). The CJK-font rationale in the Dockerfile comments (宋体/黑体 →
  Noto CJK substitution) moves verbatim to the render image.
- CI (`.github/workflows/build-and-push.yml`) builds one image on
  default-branch push + `v*` tags; TCR personal edition creates repos on
  first push, so `law-bench/law-render` needs no registry-side setup.
- Deploy: ArgoCD watches Gitee; a roll = manifest tag bump + Gitee push.

## Goals / Non-Goals

**Goals:**

- One shared render pod that any in-cluster app can call; app images ship
  without LibreOffice.
- Zero behavior change for callers — same error contract
  (`ConverterNotAvailableError` on unavailable backend), same output paths.
- Local/dev workflows unaffected (default backend stays `libreoffice`).

**Non-Goals:**

- No format support beyond DOCX→PDF (no XLSX, no PPT, no merge/split).
- No auth/mTLS on the service — it is cluster-internal only, never exposed
  through Kong/Ingress.
- No queueing/pooling of LibreOffice workers; per-request process spawn is
  the existing model and volume is low (contract PDFs on demand).
- No change to `mcp-deployment.yaml` (legacy Harbor path, already stale).

## Decisions

**D1 — Service shape: in-repo FastAPI app, own slim image.**
`src/render_service/app.py` (~100 lines: FastAPI + two routes). New
`Dockerfile.render`: `python:3.12-slim` + apt `libreoffice-writer
fonts-noto-cjk` + `pip install fastapi uvicorn python-multipart` (pinned).
Three deps, no uv.lock coupling, no app code beyond the service module.
Alternative: a separate repo/pipeline — rejected: one more repo to govern
for ~100 lines; the monorepo already builds multiple images
(law-template, copilot-runtime, review-backend).
Alternative: reuse the law-template venv via uv — rejected: drags the whole
app dependency tree into the render image for no benefit.

**D2 — API: `POST /convert` multipart → PDF bytes; `GET /health`.**
Request: multipart field `file` (the DOCX). Response: 200
`application/pdf` (raw bytes). Errors: 400 missing/non-DOCX field, 413 over
limit (`RENDER_MAX_UPLOAD_MB`, default 50), 500 conversion failure with JSON
body. No file written outside the request's temp dir; temp dir removed in a
`finally`. Filename extension check only for the 400 case — content sniffing
beyond that is not worth it (LibreOffice failing on garbage is a 500, which
the spec allows).
Alternative: JSON base64 — rejected: multipart is the natural shape, httpx
client code is symmetric either way.

**D3 — Per-request isolation via temp workspace + LO profile.**
Each conversion runs in `tempfile.TemporaryDirectory()` with its own
`-env:UserInstallation=file://<tmp>/profile` — same trick the current
`LibreOfficeConverter` uses (`/tmp/lo-profile-<pid>`), generalized to
per-request because one pod now serves concurrent requests. uvicorn workers:
1 (async app; the subprocess conversion runs via `asyncio.to_thread` /
threadpool), replica count 1 — burst capacity if ever needed comes from
replicas, not workers.

**D4 — Client backend: `HttpRenderConverter`, name `http`, lazy failure.**
Registered in `_BACKENDS` as `"http"`. Reads `RENDER_SERVICE_URL` at
`convert()` time (not construction — matches spec scenario "no network call
at construction"; also makes env flips visible without process restart
during tests). Sends the DOCX as multipart, streams the response to
`out_path` (or `src.with_suffix(".pdf")`), returns the local `Path`. Maps:
URL unset / `httpx.ConnectError` / non-2xx → `ConverterNotAvailableError`
naming the endpoint or missing env var. Timeout 120 s (LibreOffice on a big
contract can take tens of seconds). `src/generator/__init__.py` exports the
new class.
Alternative: mapping service 5xx to a distinct exception — rejected: callers
today only distinguish "backend unavailable" (`ConverterNotAvailableError`)
from "conversion produced nothing"; keeping two error classes preserves
that contract.

**D5 — Env switch in deployments, not in code defaults.**
`deploy/deployment.yaml` (web + seed-db initContainers unaffected) and
`deploy/assistant-mcp-deployment.yaml` get `DOCS_PDF_BACKEND=http` +
`RENDER_SERVICE_URL=http://render-service.law-bench.svc.cluster.local:8090`.
Port 8090 (8010 is the web app). The MCP generate tool runs inside these
pods, so it inherits the switch — the MCP deployment on the stale Harbor
image simply keeps its local LibreOffice (non-goal).
`Dockerfile.review-backend` drops LibreOffice and the review backend env
gets the same pair.

**D6 — CI: repo image workflow (tcr-image-pipeline standard channel).**
Updated 2026-10-01: the original plan (extend `build-and-push.yml` with a
direct second push to ccr) is obsolete — direct US→ccr pushes crawl at
~0.14MB/s and were abandoned fleet-wide. law-bench is onboarded onto the
standard `image.yml` channel: matrix over `law-template` (Dockerfile) and
`law-render` (Dockerfile.render), push to `hkccr.ccs.tencentyun.com`
(11.6MB/s transpacific leg, secrets `TCR_USERNAME`/`TCR_PASSWORD`, tags
`sha-<short>` + `main`, `provenance: false`), then the cheap-3 tcr-relay
backfills ccr within its 5-minute cron cycle (repos.conf lists both repos).
Nodes pull from ccr with node-level registries.yaml auth — no per-pod
imagePullSecret required (existing `tcr-pull` refs are harmless).
Alternative: separate workflow — rejected: same triggers, same login, the
matrix keeps it one file. Alternative: multi-target single image — rejected:
one image carrying both the app and LibreOffice is exactly what we are
deleting. Layer policy: no single RUN layer above ~300MB (transpacific blob
uploads wedge); law-render's apt installs are split into two RUNs, and the
slim law-template's venv layer (~370MB uncompressed, ~150MB compressed)
stays a single `uv sync` layer.

**D7 — Deploy manifest: `deploy/render-service-deployment.yaml` + Service.**
Namespace `law-bench`, `imagePullSecrets: tcr-pull`, image
`ccr.ccs.tencentyun.com/law-bench/law-render:sha-<x>`, no node pin (no data
dependencies), no PVC, requests/limits modest (256Mi/500m request — LO
spikes on big CJK docs), readiness+liveness on `/health`, 1 replica.
ArgoCD picks it up as part of the existing app once the file lands on Gitee.

## Risks / Trade-offs

- [Network hop adds latency & a new failure mode] → same error class at the
  caller as a missing `soffice` binary today; `RENDER_SERVICE_URL` naming in
  the error makes the cause obvious; timeout bounded at 120 s.
- [Render pod down = no PDFs anywhere] → readiness probe keeps it out of
  the Service endpoints when broken; rollback path (below) restores the
  previous fat image which converts locally.
- [One replica is a single point of failure] → acceptable at current volume
  (on-demand contract PDFs); scaling = bump replicas, no code change.
- [Slimmed web image can't fall back to local LibreOffice] → deliberate:
  rollback = repoint manifest at the previous `sha-<x>` fat tag still in
  TCR (dual-track philosophy, no rebuild). Record: after this change, every
  future web-image tag must assume rendering is remote.
- [Review-backend build still needs gcc/libpq-dev] → out of scope; only its
  LibreOffice layer is removed.
- [TCR personal edition: a second repo consumes the free quota] → personal
  edition allows up to 3 repos... currently used: `law-template` (TCR),
  plus Harbor-side repos don't count. Verify quota at apply time; if
  blocked, `law-bench/law-render` → reuse... (contingency: push under
  `law-bench/render` is still one repo; quota is per-repo count, not name).

## Migration Plan

Order matters; each step is independently rollable via Gitee manifest bump:

1. Merge code (backend + service + tests). No behavior change yet — nothing
   selects `http`.
2. CI now also publishes `law-render` from the same commit. Verify both
   tags exist in TCR.
3. Deploy render-service manifest (`sha-<x>` = first image built with the
   service). Verify `/health` and a manual `/convert` round-trip from the
   web pod.
4. Web + assistant-MCP env switch (`DOCS_PDF_BACKEND=http`,
   `RENDER_SERVICE_URL=...`) — still on the fat image; verify PDF
   generation end-to-end through the service.
5. Slim the web Dockerfile (drop apt layer) — next `law-template` build;
   roll via tag bump. review-backend similarly.
6. Remove nothing historical: old fat tags stay in TCR for rollback.

Rollback at any step: flip the affected manifest's env (steps 3–4) or image
tag (step 5) back to the previous `sha-<x>`; no rebuild ever needed.

## Open Questions

- Exact TCR personal-edition repo quota confirmation (Risk above) — check
  at apply time; contingency noted, does not change the design.
- `RENDER_MAX_UPLOAD_MB` default (50) — confirm no generated contract DOCX
  exceeds it during apply; adjust via env if needed.
