"""Library registry page (admin): create a library, add sources, subscribe a domain.

The point of this page is that registering a corpus stops being a shell script
run inside a pod. Three claims are pinned:

- an external library **cannot** be created without naming its environment
  variable (the page has no field for a DSN or a key, by design);
- an illegal backend is refused with the legal values named;
- a source's ``match`` predicate round-trips as JSON, and a malformed one is
  refused rather than silently stored as an empty rule (an empty rule means
  "the whole collection", so a typo would widen the corpus instead of failing).
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import libraries, templates
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(
        conn=empty_db, name="tpl", created_by="t",
        schema={
            "entity_types": ["clause"], "concept_structures": {"clause": ["id"]},
            "relationship_kinds": ["cites_law"], "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": ["external"]},
        },
    )
    empty_db.execute(
        "INSERT INTO domains (key, name, template_id, template_version, created_by, path) "
        "SELECT 'legal','法律域',id,1,'t','legal' FROM ontology_templates ORDER BY id LIMIT 1"
    )
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _client(db, *, scopes=("admin",)) -> TestClient:
    app = create_app()
    user = User(sub="admin-1", name="a", email="a@example.com", scopes=list(scopes),
                channel="test")

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def test_page_renders_and_shows_registered_libraries(conn):
    libraries.create_library(conn, library_key="law-library", name="法规大库", created_by="t",
                             backend="qdrant", embedding_model="Qwen/Qwen3-Embedding-0.6B",
                             dims=1024,
                             location={"url_env": "QDRANT_URL", "collection": "law_chunks_v2"})
    with _client(conn) as c:
        r = c.get("/admin/libraries")
    assert r.status_code == 200
    assert "law-library" in r.text and "qdrant" in r.text
    # The form asks for the env var NAME — the value never appears on the page.
    assert "QDRANT_URL" in r.text


def test_external_library_needs_an_env_name(conn):
    with _client(conn) as c:
        r = c.post("/admin/libraries", data={
            "library_key": "bad", "name": "bad", "backend": "qdrant",
            "dims": "1024", "collection": "law_chunks_v2",  # url_env missing
        }, follow_redirects=False)
    assert r.status_code == 303
    assert "library_create_failed" in r.headers["location"]
    assert libraries.get_library(conn, library_key="bad") is None


def test_illegal_backend_is_refused_with_legal_values(conn):
    with _client(conn) as c:
        r = c.post("/admin/libraries", data={
            "library_key": "weird", "name": "w", "backend": "faiss", "dims": "1024",
        }, follow_redirects=False)
    assert r.status_code == 303
    assert "library_create_failed" in r.headers["location"]
    assert libraries.get_library(conn, library_key="weird") is None


def test_owned_library_can_be_created_without_location(conn):
    with _client(conn) as c:
        r = c.post("/admin/libraries", data={
            "library_key": "contracts", "name": "合同样本", "backend": "array-cosine",
            "dims": "2048",
        }, follow_redirects=False)
    assert r.status_code == 303
    lib = libraries.get_library(conn, library_key="contracts")
    assert lib["backend"] == "array-cosine" and lib["location"] == {}


def test_source_match_predicate_round_trips(conn):
    libraries.create_library(conn, library_key="law-library", name="法规大库", created_by="t",
                             backend="qdrant", dims=1024,
                             location={"url_env": "QDRANT_URL", "collection": "law_chunks_v2"})
    with _client(conn) as c:
        r = c.post("/admin/libraries/law-library/sources", data={
            "source_key": "local",
            "uri": "collection:law_chunks_v2#local",
            "source_kind": "payload-filter",
            "match": '{"category": ["地方性法规", "地方法规"]}',
        }, follow_redirects=False)
    assert r.status_code == 303
    lib = libraries.get_library(conn, library_key="law-library")
    srcs = libraries.list_sources(conn, library_id=lib["id"])
    assert srcs[0]["ingest_rule"]["match"] == {"category": ["地方性法规", "地方法规"]}


def test_malformed_match_is_refused_not_stored_as_whole_collection(conn):
    """An unparseable rule must not degrade to `{}` — that means "everything"."""
    libraries.create_library(conn, library_key="law-library", name="法规大库", created_by="t",
                             backend="qdrant", dims=1024,
                             location={"url_env": "QDRANT_URL", "collection": "law_chunks_v2"})
    with _client(conn) as c:
        r = c.post("/admin/libraries/law-library/sources", data={
            "source_key": "local", "uri": "x", "match": "{category: local}",
        }, follow_redirects=False)
    assert "library_source_failed" in r.headers["location"]
    lib = libraries.get_library(conn, library_key="law-library")
    assert libraries.list_sources(conn, library_id=lib["id"]) == []


def test_subscribe_grants_a_domain_and_rejects_unknown_source(conn):
    libraries.create_library(conn, library_key="law-library", name="法规大库", created_by="t",
                             backend="qdrant", dims=1024,
                             location={"url_env": "QDRANT_URL", "collection": "law_chunks_v2"})
    libraries.add_source(conn, library_key="law-library", source_key="statutes",
                         uri="x", created_by="t")
    with _client(conn) as c:
        ok = c.post("/admin/libraries/law-library/subscribe",
                    data={"domain_key": "legal", "sources": "statutes"},
                    follow_redirects=False)
        bad = c.post("/admin/libraries/law-library/subscribe",
                     data={"domain_key": "legal", "sources": "ghost"},
                     follow_redirects=False)
    assert ok.status_code == 303 and "library_subscribed" in ok.headers["location"]
    assert "library_subscribe_failed" in bad.headers["location"]
    scope = libraries.effective_sources(conn, domain_path="legal")
    assert scope == {"law-library": {"statutes"}}


def test_non_admin_is_refused(conn):
    with _client(conn, scopes=("read",)) as c:
        r = c.get("/admin/libraries", follow_redirects=False)
    assert r.status_code in (401, 403)
