"""Tests for the shared render service (``src.render_service.app``)."""

import shutil
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from pypdf import PdfReader
from fastapi.testclient import TestClient

from src.generator import create_docx
from src.render_service import app as render_app
from src.render_service.app import app

SOFFICE_AVAILABLE = shutil.which("soffice") is not None

client = TestClient(app)


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "".join(page.extract_text() or "" for page in reader.pages)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_missing_file_field_is_400():
    resp = client.post("/convert", files={"not_file": ("c.docx", b"x")})
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_non_docx_filename_is_400(tmp_path):
    resp = client.post("/convert", files={"file": ("c.txt", b"not a docx")})
    assert resp.status_code == 400


def test_oversized_upload_is_413(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER_MAX_UPLOAD_MB", "1")
    big = b"x" * (1536 * 1024)  # 1.5 MB > 1 MB limit
    resp = client.post("/convert", files={"file": ("c.docx", big)})
    assert resp.status_code == 413


def test_conversion_failure_is_500_and_service_survives(tmp_path, monkeypatch):
    def boom(docx_path, out_path):
        raise RuntimeError("soffice exited 1")

    monkeypatch.setattr(render_app, "convert_with_soffice", boom)
    p = create_docx("# 标题", tmp_path / "c.docx")
    resp = client.post("/convert", files={"file": ("c.docx", p.read_bytes())})
    assert resp.status_code == 500
    assert "conversion failed" in resp.json()["detail"]
    # The service keeps serving after a failed conversion.
    assert client.get("/health").status_code == 200


@pytest.mark.skipif(not SOFFICE_AVAILABLE, reason="libreoffice (soffice) not installed")
def test_convert_round_trip(tmp_path):
    p = create_docx("# 服务协议\n\n正文内容测试段落。", tmp_path / "c.docx")
    resp = client.post("/convert", files={"file": ("c.docx", p.read_bytes())})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content[:5] == b"%PDF-"
    assert "正文内容测试段落" in _pdf_text(resp.content)


@pytest.mark.skipif(not SOFFICE_AVAILABLE, reason="libreoffice (soffice) not installed")
def test_cjk_fidelity_no_tofu(tmp_path):
    """A Chinese 宋体-declaring contract renders extractable text, no tofu."""
    p = create_docx(
        "# 合同标题\n\n甲方与乙方就法律服务事宜达成如下协议，特此签署。",
        tmp_path / "cjk.docx",
    )
    resp = client.post("/convert", files={"file": ("cjk.docx", p.read_bytes())})
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    # Tofu (.notdef glyphs) breaks text extraction; the contract body must
    # survive the round trip.
    assert "甲方与乙方" in text
    assert "特此签署" in text


@pytest.mark.skipif(not SOFFICE_AVAILABLE, reason="libreoffice (soffice) not installed")
def test_concurrent_conversions_are_isolated(tmp_path):
    docs = {}
    for name, body in (("甲甲甲", "第一份文档的正文内容甲"), ("乙乙乙", "第二份文档的正文内容乙")):
        p = create_docx(f"# {name}\n\n{body}", tmp_path / f"{name}.docx")
        docs[name] = (f"{name}.docx", p.read_bytes(), body)

    def post(name):
        with TestClient(app) as c:
            resp = c.post("/convert", files={"file": docs[name][:2]})
        return name, resp

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(post, docs))

    for name, resp in results:
        assert resp.status_code == 200
        text = _pdf_text(resp.content)
        assert docs[name][2] in text
        other = "乙乙乙" if name == "甲甲甲" else "甲甲甲"
        assert other not in text
