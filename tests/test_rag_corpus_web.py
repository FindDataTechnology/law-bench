"""Web tests for the domain RAG surface (change
``add-domain-rag-corpus-service``, OpenSpec tasks 2.1/2.2/3.3).

Covers:

- ``/api/search`` domain param: absent domain keeps the legacy call shape
  byte-compat (no ``index_name`` kwarg, no DB touch); an unregistered domain
  is an honest 400 naming the domain; API-key identities are PINNED to the
  default legal path regardless of the param (the decision recorded in
  ``src/web/routes/search.py``'s docstring — the public read-only replica
  serves the default corpus only); anonymous identities get 401; the two
  gates compose in order (platform scope first, then domain membership) and
  a member reads the domain's REGISTERED index.
- admin RAG register/ingest routes: admin scope + domain lead two-gate
  composition, flash keys (``flash.rag_registered`` / ``flash.rag_sources_invalid``
  / ``flash.rag_register_failed`` / ``flash.rag_ingest_started`` /
  ``flash.rag_ingest_failed``), kernel ValueError detail riding the failure
  flash, and the fire-and-forget ingest thread (``run_ingest`` monkeypatched
  so no real thread work / ES / MinIO happens).

Style: ``tests/test_admin_web.py`` — ``_client(db, user)`` builds
``create_app()`` with ``dependency_overrides`` for ``get_db`` +
``get_current_user`` (the override also stamps ``request.state.user``).

Elasticsearch note: ``src.search.query.search`` and
``src.search.ingest.run_ingest`` are monkeypatched everywhere (pytest
``monkeypatch`` fixture); nothing here requires a live ES or MinIO.

Locale: flash keys are asserted via the redirect URL's ``msg=flash.*`` query
param (locale-independent by design); the one zh literal asserted
(「该域未登记 RAG 语料」) is a route constant, not an i18n catalog string.

Seed data goes through the C1 kernel APIs (``src.bench.templates`` /
``src.bench.workspaces``) and ``src.search.resolver.register_corpus``.

DB note: the ``/api/search`` route borrows its connection via a direct
``get_db()`` call (not a FastAPI dependency), which resolves to the
process-wide shared autocommit connection against the ``database_url`` env —
i.e. the same session DB the ``seeded_db`` fixture seeds. Everything the
gates read (domains, memberships, rag_corpora) is committed by the kernel
APIs, so the route's own connection sees it.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import templates as bench_templates
from src.bench import workspaces
from src.search import resolver
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

# A structurally complete template schema (C1 kernel requirement).
VALID_SCHEMA = {
    "entity_types": ["company"],
    "concept_structures": {"indicator": ["name", "unit"]},
    "relationship_kinds": ["belongs_to"],
    "tier_vocabulary": ["gold", "silver", "bronze", "raw"],
    "sensitivity_vocabulary": ["public", "internal", "confidential"],
    "corpus_declaration": {"source_types": []},
}


# --- seed + client helpers -------------------------------------------------- #


def _seed_domain(conn, key: str) -> dict:
    """One domain via the C1 APIs (template + instantiation)."""
    bench_templates.create_template(
        conn, name=f"tpl-{key}", schema=dict(VALID_SCHEMA), created_by="seed"
    )
    return workspaces.instantiate_domain(
        conn, key=key, name=f"域{key}",
        template_name=f"tpl-{key}", template_version=None, created_by="seed",
    )


def _register(conn, key: str, index_name: str) -> dict:
    """Register a corpus for an existing domain via the kernel API."""
    return resolver.register_corpus(
        conn, domain_key=key, index_name=index_name,
        sources=[{"bucket": f"{key}-bucket", "prefix": f"{key}/"}],
        registered_by="seed",
    )


def _user(sub: str, scopes: list[str], channel: str = "test") -> User:
    """Override-pattern identity; ``email`` feeds the operator stamp."""
    return User(
        sub=sub, name=sub, email=f"{sub}@example.com",
        scopes=list(scopes), channel=channel,
    )


def _client(db, user: User) -> TestClient:
    """App with ``get_db`` + ``get_current_user`` overridden to ``user``.

    The override mirrors the real dependency's chrome contract by setting
    ``request.state.user`` (the search route reads exactly that attribute).
    """
    app = create_app()

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    """Neutralize the fail-closed startup IdP probe for every app built here."""
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _params(location: str) -> dict:
    """Decode the flash redirect's query params (msg / err / detail / ...)."""
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def _stub_search(monkeypatch) -> list[dict]:
    """Replace ``src.search.query.search`` with a recording fake.

    Records ``{"query", "top_k", **extra_kwargs}`` per call, so the legacy
    call shape is observable as the ABSENCE of an ``index_name`` key — the
    byte-compat red line for the no-domain path.
    """
    calls: list[dict] = []

    def fake_search(query, top_k=5, **kwargs):
        calls.append({"query": query, "top_k": top_k, **kwargs})
        return [
            {"text": f"hit for {query}", "source_path": "x.md", "score": 0.9}
        ]

    monkeypatch.setattr("src.search.query.search", fake_search)
    return calls


def _stub_run_ingest(monkeypatch) -> tuple[list[tuple], threading.Event]:
    """Replace ``src.search.ingest.run_ingest`` with a recording fake.

    The admin route's daemon thread resolves ``run_ingest`` at thread-run
    time (lazy import inside the closure), so patching the module attribute
    before the request fully prevents real thread work. Returns the call
    recorder plus an Event the fake sets, for a deterministic wait.
    """
    calls: list[tuple] = []
    done = threading.Event()

    def fake_run_ingest(domain_key, prefix=None, conn=None):
        calls.append((domain_key, prefix))
        done.set()
        return {"documents": 0, "chunks": 0, "errors": 0}

    monkeypatch.setattr("src.search.ingest.run_ingest", fake_run_ingest)
    return calls, done


# =========================================================================== #
# /api/search: legacy byte-compat (缺参 legal 零变化, task 3.3)                  #
# =========================================================================== #


def test_api_search_without_domain_keeps_legacy_call_shape(seeded_db, monkeypatch):
    """No ``domain`` param -> the legacy path verbatim, even when a registered
    domain exists: no index_name kwarg, no gate, 200 with the same shape."""
    _seed_domain(seeded_db, "fin")
    _register(seeded_db, "fin", "fin-rag")  # registered, yet must be ignored
    calls = _stub_search(monkeypatch)
    with _client(seeded_db, _user("reader", ["content:read"])) as c:
        r = c.get("/api/search?q=保密义务")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["source_path"] == "x.md"  # same response shape
    assert calls == [{"query": "保密义务", "top_k": 5}]  # no index_name kwarg


# =========================================================================== #
# /api/search: unregistered domain (未登记域如实) + credential channels         #
# =========================================================================== #


def test_api_search_unregistered_domain_is_honest_400(seeded_db, monkeypatch):
    """Existing-but-unregistered domain -> 400 JSON naming the domain — never
    a 404, never a search against another domain's index."""
    _seed_domain(seeded_db, "fin")  # exists, never registered
    calls = _stub_search(monkeypatch)
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.get("/api/search?q=x&domain=fin")
    assert r.status_code == 400
    error = r.json()["error"]
    assert "fin" in error and "no registered RAG corpus" in error
    assert calls == []  # zero exposure: nothing ran


def test_api_search_apikey_channel_is_pinned_to_default_path(seeded_db, monkeypatch):
    """API-key identities are pinned to the default (legal) path REGARDLESS
    of the domain param — the decision documented in search.py's docstring.

    Even an UNREGISTERED domain must not 400 (nor 401): the public read-only
    replica serves the default corpus only and never enforces workspace
    membership, so a non-legal domain is ignored there.
    """
    calls = _stub_search(monkeypatch)
    with _client(seeded_db, _user("key-user", ["content:read"], channel="apikey")) as c:
        r = c.get("/api/search?q=x&domain=ghost")
    assert r.status_code == 200
    assert calls and "index_name" not in calls[0]  # legacy call shape taken


def test_api_search_anonymous_domain_request_is_401(seeded_db, monkeypatch):
    """No authenticated identity + non-default domain -> 401, fail closed."""
    calls = _stub_search(monkeypatch)
    with _client(seeded_db, _user("", [], channel="anonymous")) as c:
        r = c.get("/api/search?q=x&domain=fin")
    assert r.status_code == 401
    assert calls == []


# =========================================================================== #
# /api/search: two-gate composition (平台 scope -> 域成员, task 3.3)             #
# =========================================================================== #


def test_api_search_registered_domain_non_member_403(seeded_db, monkeypatch):
    """Platform scope passes but no membership -> 403 无该域权限, zero runs."""
    domain = _seed_domain(seeded_db, "fin")
    _register(seeded_db, "fin", "fin-rag")
    assert domain["key"] == "fin"
    calls = _stub_search(monkeypatch)
    with _client(seeded_db, _user("outsider", ["content:read", "content:write"])) as c:
        r = c.get("/api/search?q=x&domain=fin")
    assert r.status_code == 403
    assert r.json()["detail"] == "无该域权限"
    assert calls == []


def test_api_search_domain_member_reads_registered_index(seeded_db, monkeypatch):
    """Gate 2 passes (annotator member) -> 200, searched on the REGISTERED
    index (resolve_index's value, not the global default)."""
    domain = _seed_domain(seeded_db, "fin")
    workspaces.add_member(
        seeded_db, domain_id=domain["id"], user_id="ann-1",
        role="annotator", added_by="seed",
    )
    _register(seeded_db, "fin", "fin-rag")
    calls = _stub_search(monkeypatch)
    with _client(seeded_db, _user("ann-1", ["content:read"])) as c:
        r = c.get("/api/search?q=x&domain=fin")
    assert r.status_code == 200
    assert calls == [{"query": "x", "top_k": 5, "index_name": "fin-rag"}]


def test_api_search_scope_gate_runs_before_domain_gate(seeded_db, monkeypatch):
    """Gate order: a member WITHOUT the platform scope gets the scope denial
    (gate 1), not the domain denial — scope composes first."""
    domain = _seed_domain(seeded_db, "fin")
    workspaces.add_member(
        seeded_db, domain_id=domain["id"], user_id="ann-2",
        role="annotator", added_by="seed",
    )
    _register(seeded_db, "fin", "fin-rag")
    calls = _stub_search(monkeypatch)
    with _client(seeded_db, _user("ann-2", ["content:write"])) as c:
        r = c.get("/api/search?q=x&domain=fin")
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: content:read"
    assert calls == []


# =========================================================================== #
# admin RAG register (登记与管理走 admin 面 + lead 合成执法, design D5)          #
# =========================================================================== #


def test_admin_rag_register_stores_corpus_row(seeded_db):
    """Admin (no membership — platform-gate bypass) posts the form -> the row
    lands in rag_corpora with normalized sources + operator stamp."""
    _seed_domain(seeded_db, "fin")
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.post(
            "/admin/domains/fin/rag/register",
            data={
                "index_name": "fin-rag",
                "sources": '[{"bucket": "bk", "prefix": "docs/"}]',
                "embedding_model": "",
            },
            follow_redirects=False,
        )
    assert r.status_code == 303
    params = _params(r.headers["location"])
    assert params["msg"] == "flash.rag_registered"
    assert "err" not in params

    row = resolver.get_corpus(seeded_db, domain_key="fin")
    assert row["index_name"] == "fin-rag"
    assert row["sources"] == [{"bucket": "bk", "prefix": "docs/"}]
    assert row["registered_by"] == "admin-u@example.com"


def test_admin_rag_register_invalid_sources_flash(seeded_db):
    """Malformed sources JSON (and a non-array JSON value) -> the dedicated
    flash.rag_sources_invalid, no row stored."""
    _seed_domain(seeded_db, "fin")
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r1 = c.post(
            "/admin/domains/fin/rag/register",
            data={"index_name": "fin-rag", "sources": '[{"bucket": '},
            follow_redirects=False,
        )
        r2 = c.post(
            "/admin/domains/fin/rag/register",
            data={"index_name": "fin-rag", "sources": '{"bucket": "x"}'},
            follow_redirects=False,
        )
    for r in (r1, r2):
        assert r.status_code == 303
        params = _params(r.headers["location"])
        assert params["msg"] == "flash.rag_sources_invalid"
        assert params["err"] == "1"
        assert params["detail"]  # the parse/shape problem rides the flash
    assert resolver.get_corpus(seeded_db, domain_key="fin") is None


def test_admin_rag_register_prefix_violation_flash_with_kernel_detail(seeded_db):
    """A kernel ValueError (index-name convention) -> flash.rag_register_failed
    with the kernel's message naming the required prefix."""
    _seed_domain(seeded_db, "fin")
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.post(
            "/admin/domains/fin/rag/register",
            data={"index_name": "legal-rag", "sources": "[]"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    params = _params(r.headers["location"])
    assert params["msg"] == "flash.rag_register_failed"
    assert params["err"] == "1"
    assert "must start with 'fin-'" in params["detail"]  # kernel detail intact
    assert resolver.get_corpus(seeded_db, domain_key="fin") is None


def test_admin_rag_register_requires_admin_scope(seeded_db):
    """A domain lead WITHOUT the admin platform scope is 403 at gate 1 — the
    registry shapes the platform's retrieval surface, so platform-gate is
    raised to ``admin`` (a mere lead cannot register)."""
    domain = _seed_domain(seeded_db, "fin")
    workspaces.add_member(
        seeded_db, domain_id=domain["id"], user_id="lead-fin",
        role="lead", added_by="seed",
    )
    with _client(
        seeded_db, _user("lead-fin", ["content:read", "content:write"])
    ) as c:
        r = c.post(
            "/admin/domains/fin/rag/register",
            data={"index_name": "fin-rag", "sources": "[]"},
            follow_redirects=False,
        )
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: admin"
    assert resolver.get_corpus(seeded_db, domain_key="fin") is None


def test_admin_rag_register_lead_with_admin_scope_allowed(seeded_db):
    """Two-gate composition: a domain lead holding the (non-wildcard) admin
    platform scope passes BOTH gates and registers the corpus."""
    domain = _seed_domain(seeded_db, "fin")
    workspaces.add_member(
        seeded_db, domain_id=domain["id"], user_id="lead-fin",
        role="lead", added_by="seed",
    )
    with _client(seeded_db, _user("lead-fin", ["admin", "content:read"])) as c:
        r = c.post(
            "/admin/domains/fin/rag/register",
            data={"index_name": "fin-rag", "sources": "[]"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert _params(r.headers["location"])["msg"] == "flash.rag_registered"
    row = resolver.get_corpus(seeded_db, domain_key="fin")
    assert row["index_name"] == "fin-rag"
    assert row["registered_by"] == "lead-fin@example.com"  # lead's own stamp


# =========================================================================== #
# admin RAG ingest (fire-and-forget thread, design D6 风险③)                    #
# =========================================================================== #


def test_admin_rag_ingest_registered_domain_fires_background_thread(
    seeded_db, monkeypatch
):
    """Registered corpus: flash started, and the daemon thread actually fires
    ``run_ingest`` with the form's prefix (patched before the request)."""
    domain = _seed_domain(seeded_db, "fin")
    workspaces.add_member(
        seeded_db, domain_id=domain["id"], user_id="lead-fin",
        role="lead", added_by="seed",
    )
    _register(seeded_db, "fin", "fin-rag")
    calls, done = _stub_run_ingest(monkeypatch)

    with _client(seeded_db, _user("lead-fin", ["admin", "content:read"])) as c:
        r = c.post(
            "/admin/domains/fin/rag/ingest",
            data={"prefix": "cust/"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert _params(r.headers["location"])["msg"] == "flash.rag_ingest_started"
        assert done.wait(timeout=10)  # deterministic: the thread ran the fake

    assert calls == [("fin", "cust/")]


def test_admin_rag_ingest_unregistered_domain_flash_failed(seeded_db, monkeypatch):
    """未登记域如实: no corpus -> flash.rag_ingest_failed with the honest
    detail, and NO thread is ever started."""
    _seed_domain(seeded_db, "fin")  # exists, never registered
    calls, _done = _stub_run_ingest(monkeypatch)
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.post(
            "/admin/domains/fin/rag/ingest", data={}, follow_redirects=False
        )
    assert r.status_code == 303
    params = _params(r.headers["location"])
    assert params["msg"] == "flash.rag_ingest_failed"
    assert params["err"] == "1"
    assert params["detail"] == "该域未登记 RAG 语料"
    time.sleep(0.2)  # belt-and-braces: nothing may fire asynchronously
    assert calls == []


def test_admin_rag_ingest_requires_admin_scope(seeded_db, monkeypatch):
    """Ingest is registry-shaping too: a non-admin user is 403 at gate 1 and
    no thread fires."""
    _seed_domain(seeded_db, "fin")
    calls, _done = _stub_run_ingest(monkeypatch)
    with _client(
        seeded_db, _user("writer", ["content:read", "content:write"])
    ) as c:
        r = c.post(
            "/admin/domains/fin/rag/ingest", data={}, follow_redirects=False
        )
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: admin"
    assert calls == []
