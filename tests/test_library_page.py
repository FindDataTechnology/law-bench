"""The corpus-documents page: browse by document, take a document, take articles.

What this page must not do, and is checked here:

- present an unreachable store as an empty catalog;
- offer write buttons to a reader;
- let the reader take a document from a source that declared no document shape.
"""

from __future__ import annotations

import re

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import libraries, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.search import library_index
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

SCHEMA = {
    "entity_types": ["law", "clause", "concept"],
    "concept_structures": {"law": ["id"], "clause": ["id"]},
    "relationship_kinds": ["defines"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": ["external"]},
}

MAPPING = {"id": "doc_key", "title": "doc_title", "text": "body", "order": "seq",
           "unit_kind": "law", "clause_kind": "clause"}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    dom = workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    for role, sub in (("expert", "u-expert"), ("annotator", "u-read")):
        workspaces.add_member(conn=empty_db, domain_id=dom["id"], user_id=sub, role=role,
                              added_by="t")
    lib = libraries.create_library(
        conn=empty_db, library_key="law-library", name="law-library", created_by="t",
        backend="qdrant", embedding_model="m", dims=1024,
        location={"url_env": "TEST_QDRANT_URL", "collection": "corpus"},
    )
    libraries.add_source(
        conn=empty_db, library_key="law-library", source_key="statutes",
        uri="collection:corpus/statutes", created_by="t", source_kind="payload-filter",
        ingest_rule={"match": {"category": ["statutes"]}, "document": MAPPING},
    )
    libraries.add_source(
        conn=empty_db, library_key="law-library", source_key="misc",
        uri="collection:corpus/misc", created_by="t", source_kind="payload-filter",
        ingest_rule={"match": {"category": ["misc"]}},
    )
    libraries.subscribe(conn=empty_db, domain_id=dom["id"], library_key="law-library",
                        created_by="t")
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


@pytest.fixture()
def fake_qdrant(monkeypatch):
    def install():
        def answer(url, *, json=None, headers=None, timeout=None):
            if url.endswith("/facet"):
                payload = {"result": {"hits": [{"value": "7", "count": 2}]}}
            else:
                payload = {"result": {"points": [
                    {"id": "7-0", "payload": {"doc_key": "7", "doc_title": "中华人民共和国合同法",
                                              "body": "第一条 内容。", "seq": 0}},
                ]}}
            return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

        monkeypatch.setattr(library_index, "_http_post", answer)
        monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")

    return install


def _client(db, sub: str) -> TestClient:
    app = create_app()
    user = User(sub=sub, name=sub, email=f"{sub}@e.com",
                scopes=["content:read", "content:write"], channel="test")

    def _cu(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _cu
    return TestClient(app)


def _body(html: str) -> str:
    i = html.find("<body")
    body = html[i:] if i >= 0 else html
    return re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def test_documents_are_listed_with_titles(conn, fake_qdrant):
    fake_qdrant()
    with _client(conn, "u-expert") as c:
        page = _body(c.get("/d/legal/library?lib=law-library&src=statutes").text)
    assert "中华人民共和国合同法" in page
    assert "取入本体" in page


def test_reader_gets_no_write_buttons(conn, fake_qdrant):
    fake_qdrant()
    with _client(conn, "u-read") as c:
        page = _body(c.get("/d/legal/library?lib=law-library&src=statutes").text)
    assert "中华人民共和国合同法" in page
    assert "取入本体" not in page


def test_unreachable_store_shows_an_error_not_an_empty_list(conn, monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(library_index, "_http_post", boom)
    monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")
    with _client(conn, "u-expert") as c:
        page = _body(c.get("/d/legal/library?lib=law-library&src=statutes").text)
    assert "读取语料失败" in page
    assert "connection refused" in page


def test_a_source_without_a_document_mapping_says_so(conn, fake_qdrant):
    fake_qdrant()
    with _client(conn, "u-expert") as c:
        page = _body(c.get("/d/legal/library?lib=law-library").text)
    assert "该来源未声明文档结构" in page


def test_adopting_a_document_redirects_with_a_flash(conn, fake_qdrant):
    fake_qdrant()
    with _client(conn, "u-expert") as c:
        resp = c.post("/d/legal/library/adopt",
                      data={"lib": "law-library", "src": "statutes", "doc": "7"},
                      follow_redirects=False)
    assert resp.status_code == 303
    assert "msg=flash.library_document_saved" in resp.headers["location"]
    row = conn.execute(
        "SELECT external_key FROM knowledge_units WHERE namespace='legal' AND kind='law'"
    ).fetchone()
    assert row["external_key"] == "合同法"
