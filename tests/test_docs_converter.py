"""Tests for the DOCX -> PDF converter (``src.generator.converter``)."""

import shutil

import httpx
import pytest

from src.generator import (
    ConverterNotAvailableError,
    Docx2PdfConverter,
    HttpRenderConverter,
    LibreOfficeConverter,
    create_docx,
    docx_to_pdf,
    get_converter,
)

SOFFICE_AVAILABLE = shutil.which("soffice") is not None


def test_get_converter_default_is_libreoffice(monkeypatch):
    monkeypatch.delenv("DOCS_PDF_BACKEND", raising=False)
    assert isinstance(get_converter(), LibreOfficeConverter)


def test_get_converter_resolves_env_var(monkeypatch):
    monkeypatch.setenv("DOCS_PDF_BACKEND", "docx2pdf")
    assert isinstance(get_converter(), Docx2PdfConverter)


def test_get_converter_rejects_unknown_backend():
    with pytest.raises(ValueError):
        get_converter("weasyprint")


def test_get_converter_resolves_http_backend(monkeypatch):
    # No RENDER_SERVICE_URL needed: constructing the backend never touches
    # the network.
    monkeypatch.setenv("DOCS_PDF_BACKEND", "http")
    assert isinstance(get_converter(), HttpRenderConverter)


def test_http_backend_requires_service_url(tmp_path, monkeypatch):
    monkeypatch.delenv("RENDER_SERVICE_URL", raising=False)
    p = create_docx("# 标题", tmp_path / "c.docx")
    with pytest.raises(ConverterNotAvailableError, match="RENDER_SERVICE_URL"):
        docx_to_pdf(p, backend="http")


def test_http_backend_convert_via_mock_transport(tmp_path):
    p = create_docx("# 标题", tmp_path / "c.docx")
    payload = b"%PDF-1.7 fake render-service output"

    def handler(request):
        assert request.url.path == "/convert"
        return httpx.Response(200, content=payload)

    converter = HttpRenderConverter(
        base_url="http://render.test",
        transport=httpx.MockTransport(handler),
    )
    pdf = converter.convert(p, out_path=tmp_path / "out.pdf")
    assert pdf == tmp_path / "out.pdf"
    assert pdf.read_bytes() == payload


def test_http_backend_non_2xx_raises(tmp_path):
    p = create_docx("# 标题", tmp_path / "c.docx")

    def handler(request):
        return httpx.Response(500, json={"detail": "conversion failed"})

    converter = HttpRenderConverter(
        base_url="http://render.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConverterNotAvailableError, match="HTTP 500"):
        converter.convert(p, out_path=tmp_path / "out.pdf")


def test_http_backend_connect_error_raises(tmp_path):
    p = create_docx("# 标题", tmp_path / "c.docx")

    def handler(request):
        raise httpx.ConnectError("connection refused")

    converter = HttpRenderConverter(
        base_url="http://render.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConverterNotAvailableError, match="unreachable"):
        converter.convert(p, out_path=tmp_path / "out.pdf")


def test_docx_to_pdf_default_output_path(tmp_path):
    if not SOFFICE_AVAILABLE:
        pytest.skip("libreoffice (soffice) not installed")
    p = create_docx("# 标题", tmp_path / "c.docx")
    pdf = docx_to_pdf(p)
    assert pdf == tmp_path / "c.pdf"
    assert pdf.exists() and pdf.stat().st_size > 0


def test_docx_to_pdf_explicit_output_path(tmp_path):
    if not SOFFICE_AVAILABLE:
        pytest.skip("libreoffice (soffice) not installed")
    p = create_docx("# 标题", tmp_path / "c.docx")
    pdf = docx_to_pdf(p, output_path=str(tmp_path / "final.pdf"))
    assert pdf == tmp_path / "final.pdf"
    assert pdf.exists() and pdf.stat().st_size > 0


def test_converter_not_available_raises(tmp_path):
    p = create_docx("# 标题", tmp_path / "c.docx")
    converter = LibreOfficeConverter(binary="soffice-definitely-missing-xyz")
    with pytest.raises(ConverterNotAvailableError):
        converter.convert(p)
