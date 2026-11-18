"""Shared document-rendering service: headless LibreOffice behind HTTP.

Extracted from the web image (extract-render-service) so application images
(web, assistant-MCP, review backend) no longer carry LibreOffice; they set
``DOCS_PDF_BACKEND=http`` + ``RENDER_SERVICE_URL`` and delegate here.

Endpoints:
- ``POST /convert`` — multipart field ``file`` carrying a ``.docx``; responds
  ``application/pdf``.
- ``GET /health`` — readiness probe target.

Each conversion runs in its own temp workspace with its own LibreOffice
profile (per-request isolation: concurrent requests never share lock or
output files). No auth: ClusterIP-only, reachable solely from inside the
cluster.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

__all__ = ["app", "convert_with_soffice"]

app = FastAPI(title="law-bench render-service")

# The soffice subprocess must finish inside the client's timeout (the
# HttpRenderConverter waits 120 s); leave the client the last 10 s to
# deliver the response.
SOFFICE_TIMEOUT_S = 110

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _max_upload_bytes() -> int:
    return int(os.environ.get("RENDER_MAX_UPLOAD_MB", "50")) * 1024 * 1024


def convert_with_soffice(docx_path: Path, out_path: Path) -> None:
    """Run one headless conversion in the file's own workspace (blocking)."""
    binary = shutil.which("soffice")
    if binary is None:
        raise RuntimeError("soffice not found on PATH")
    # Per-request profile dir (as a valid file URL for the host OS) avoids
    # headless profile/lock collisions between concurrent requests.
    profile = (docx_path.parent / "lo-profile").as_uri()
    cmd = [
        binary,
        "--headless",
        "--norestore",
        f"-env:UserInstallation={profile}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(docx_path.parent),
        str(docx_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=SOFFICE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"soffice timed out after {SOFFICE_TIMEOUT_S}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"soffice exited {exc.returncode}: {detail}") from exc
    produced = docx_path.parent / (docx_path.stem + ".pdf")
    if not produced.is_file():
        raise RuntimeError("soffice reported success but produced no PDF")
    if produced != out_path:
        shutil.move(str(produced), str(out_path))


@app.exception_handler(RequestValidationError)
async def _validation_to_400(request: Request, exc: RequestValidationError):
    # The only client contract is /convert: report a missing/malformed file
    # field as 400 (the spec's error code) instead of FastAPI's default 422.
    return JSONResponse(
        status_code=400,
        content={"detail": "multipart field 'file' with a .docx upload is required"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "render-service"}


@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    filename = file.filename or ""
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="file field must carry a .docx upload")

    limit = _max_upload_bytes()
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds RENDER_MAX_UPLOAD_MB ({limit // (1024 * 1024)} MB)",
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    with tempfile.TemporaryDirectory(prefix="render-") as tmp:
        docx = Path(tmp) / "input.docx"
        docx.write_bytes(data)
        pdf = Path(tmp) / "input.pdf"
        try:
            # soffice is a blocking subprocess: keep it off the event loop so
            # concurrent requests (health checks included) stay served.
            await asyncio.to_thread(convert_with_soffice, docx, pdf)
            content = pdf.read_bytes()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=f"conversion failed: {exc}") from exc

    return Response(content=content, media_type="application/pdf")
