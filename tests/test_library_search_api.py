"""`/api/library/search`: the machine-facing retrieval contract.

Three callers depend on telling these apart, so they are pinned as status codes:

- a hit list, possibly empty (a miss inside a real corpus);
- 400 when the domain subscribes to nothing ("nothing to search" is not "no hit");
- 502 when an upstream store or embedder fails (not the caller's mistake).

It also must not become a hole in the domain gate: the same `_effective_domain`
used by `/api/search` runs here, so an outsider cannot read another domain's
corpus through this endpoint.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import libraries, templates
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.search import embedders, library_index
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from fastapi import HTTPException
from src.web.deps import get_db


class _Stub:
    def __init__(self, answer):
        self.calls: list[dict] = []
        self._answer = answer

    def __call__(self, url, *, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "body": json})
        payload = self._answer(url, json)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(
        empty_db, name="tpl", created_by="t",
        schema={
            "entity_types": ["clause"], "concept_structures": {"clause": ["id"]},
            "relationship_kinds": ["cites_law"], "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
        },
    )
    for key, path in (("legal", "legal"), ("cr", "legal/cr"), ("bare", "bare")):
        parent = None
        if key == "cr":
            parent = empty_db.execute(
                "SELECT id FROM domains WHERE key='legal'").fetchone()["id"]
        empty_db.execute(
            "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
            "SELECT %s,%s,id,1,'t',%s,%s FROM ontology_templates ORDER BY id LIMIT 1",
            (key, key.upper(), parent, path),
        )
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    embedders.clear_cache()
    monkeypatch.setenv("TEST_QDRANT", "http://qdrant.test:6333")
    monkeypatch.setenv(embedders.LOCAL_EMBED_URL_ENV, "http://embed.test:6100")
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    yield
    embedders.clear_cache()


def _client(db, *, scopes=("*",)) -> TestClient:
    app = create_app()
    user = User(sub="u1", name="u1", email="u1@example.com", scopes=list(scopes),
                channel="test")

    def _cu(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _cu
    return TestClient(app)


def _library(conn, *, subscribe=("legal", "cr"), sources=("judicial",)) -> None:
    libraries.create_library(conn, library_key="law-library", name="法规大库", created_by="t",
                             backend="qdrant", embedding_model="Qwen/Qwen3-Embedding-0.6B",
                             dims=1024,
                             location={"url_env": "TEST_QDRANT", "collection": "law_chunks_v2"})
    for s in sources:
        libraries.add_source(conn, library_key="law-library", source_key=s, uri="x",
                             created_by="t", ingest_rule={"match": {"category": "司法解释"}})
    for key in subscribe:
        dom = conn.execute("SELECT id, path FROM domains WHERE key=%s", (key,)).fetchone()
        libraries.subscribe(conn, domain_id=dom["id"], library_key="law-library", created_by="t")
    conn.commit()


def _embed() -> _Stub:
    return _Stub(lambda url, body: {"embeddings": [[0.01] * 1024] * len(body["input"])})


def test_hits_are_returned_as_json(conn, monkeypatch):
    _library(conn)
    monkeypatch.setattr(embedders, "_http_post", _embed())
    monkeypatch.setattr(library_index, "_http_post", _Stub(lambda url, body: {"result": [
        {"id": 1, "score": 0.7617,
         "payload": {"chunk_text": "批复正文", "title": "批复", "chunk_no": 0,
                     "category": "司法解释"}},
    ]}))
    with _client(conn) as c:
        r = c.get("/api/library/search", params={"q": "优先受偿权", "domain": "legal"})
    assert r.status_code == 200
    data = r.json()
    assert data["domain"] == "legal"
    assert data["hits"][0]["source_key"] == "judicial"
    assert data["hits"][0]["text"] == "批复正文"
    assert data["hits"][0]["library_key"] == "law-library"


def test_empty_hit_list_is_200_not_an_error(conn, monkeypatch):
    _library(conn)
    monkeypatch.setattr(embedders, "_http_post", _embed())
    monkeypatch.setattr(library_index, "_http_post", _Stub(lambda url, body: {"result": []}))
    with _client(conn) as c:
        r = c.get("/api/library/search", params={"q": "无关", "domain": "legal"})
    assert r.status_code == 200
    assert r.json()["hits"] == []


def test_unsubscribed_domain_is_400(conn):
    with _client(conn) as c:
        r = c.get("/api/library/search", params={"q": "条例", "domain": "bare"})
    assert r.status_code == 400
    assert "no library subscription" in r.json()["error"]


def test_upstream_failure_is_502_not_empty(conn, monkeypatch):
    _library(conn)
    monkeypatch.setattr(embedders, "_http_post", _embed())
    monkeypatch.setattr(
        library_index, "_http_post",
        _Stub(lambda url, body: RuntimeError("connection refused")),
    )
    with _client(conn) as c:
        r = c.get("/api/library/search", params={"q": "条例", "domain": "legal"})
    assert r.status_code == 502
    assert "connection refused" in r.json()["error"]


def test_unknown_domain_is_404(conn):
    with _client(conn) as c:
        r = c.get("/api/library/search", params={"q": "x", "domain": "ghost"})
    assert r.status_code == 404


def test_empty_query_returns_empty_list_without_touching_the_store(conn, monkeypatch):
    _library(conn)
    stub = _Stub(lambda url, body: {"result": []})
    monkeypatch.setattr(library_index, "_http_post", stub)
    with _client(conn) as c:
        r = c.get("/api/library/search", params={"q": "", "domain": "legal"})
    assert r.json() == []
    assert stub.calls == []


def test_child_sees_the_parent_grant(conn, monkeypatch):
    """`cr` inherits `legal`'s subscription; the API must honour that."""
    _library(conn, subscribe=("legal",))
    monkeypatch.setattr(embedders, "_http_post", _embed())
    monkeypatch.setattr(library_index, "_http_post", _Stub(lambda url, body: {"result": []}))
    with _client(conn) as c:
        r = c.get("/api/library/search", params={"q": "条例", "domain": "cr"})
    assert r.status_code == 200


def test_domain_gate_still_applies(conn, monkeypatch):
    """The shared gate must run: an outsider cannot read another domain's corpus."""
    _library(conn)
    monkeypatch.setattr(embedders, "_http_post", _embed())
    stub = _Stub(lambda url, body: {"result": []})
    monkeypatch.setattr(library_index, "_http_post", stub)
    from src.web.routes import search as search_routes

    def deny(*a, **kw):
        raise HTTPException(status_code=403, detail="not a member")

    monkeypatch.setattr(search_routes, "_effective_domain", deny)
    with _client(conn) as c:
        r = c.get("/api/library/search", params={"q": "条例", "domain": "legal"})
    assert r.status_code in (401, 403, 500)
    assert stub.calls == []
