"""HTML tests for the contract-template web routes (``/contracts``,
``/contracts/{type}``, ``/contracts/{type}/download/{format}``) and the nav link.

The contracts routes are file-backed (they read ``src/contracts`` + the bundled
``output/law_info`` markdown), so these tests use a lightweight DB-free
``TestClient`` - no PostgreSQL fixture is required. Auth is bypassed the same
way ``conftest.app_client`` does it: the fail-closed IdP startup probe
(``logto.verify_reachable``) is neutralized so ``create_app()`` boots, and
``get_current_user`` is overridden to a stub so the constructor-level auth
dependency lets every protected route through without per-test tokens.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user

SOFFICE_AVAILABLE = shutil.which("soffice") is not None


def _test_user() -> User:
    """Stub authenticated user — mirrors conftest._test_user (kept local so this
    file stays independent of conftest internals)."""
    return User(
        sub="test-user",
        name="Test User",
        email="test@example.com",
        scopes=["*"],
        channel="test",
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    app = create_app()
    app.dependency_overrides[get_current_user] = _test_user
    with TestClient(app) as c:
        yield c


def test_contracts_list(client: TestClient):
    r = client.get("/contracts")
    assert r.status_code == 200
    assert "买卖合同" in r.text
    assert "/contracts/sale" in r.text


def test_contract_detail(client: TestClient):
    r = client.get("/contracts/sale")
    assert r.status_code == 200
    # template body rendered (markdown -> heading)
    assert "<h2>" in r.text or "第一条" in r.text
    # a slot-instruction label is shown
    assert "甲方名称" in r.text
    # a 法律法规 name from the sale answers is shown
    assert "民法典" in r.text
    # download links present
    assert "/contracts/sale/download/docx" in r.text
    assert "/contracts/sale/download/pdf" in r.text
    # generation-principle section is shown
    assert "生成原理" in r.text


def test_contract_detail_unknown_type_404(client: TestClient):
    r = client.get("/contracts/does_not_exist")
    assert r.status_code == 404
    assert "does_not_exist" in r.text


def test_contract_download_docx(client: TestClient):
    r = client.get("/contracts/sale/download/docx")
    assert r.status_code == 200
    assert "wordprocessingml" in r.headers.get("content-type", "")


def test_contract_download_unsupported_format_400(client: TestClient):
    r = client.get("/contracts/sale/download/rtf")
    assert r.status_code == 400


def test_contract_download_unknown_type_404(client: TestClient):
    r = client.get("/contracts/does_not_exist/download/pdf")
    assert r.status_code == 404


@pytest.mark.skipif(not SOFFICE_AVAILABLE, reason="libreoffice (soffice) not installed")
def test_contract_download_pdf(client: TestClient):
    r = client.get("/contracts/sale/download/pdf")
    assert r.status_code == 200
    assert "application/pdf" in r.headers.get("content-type", "")


def test_contracts_nav_link_present(client: TestClient):
    r = client.get("/contracts")
    assert '/contracts"' in r.text or "合同模板" in r.text
