"""The ontology page (§4): list, gaps, smoke data, and forms only for writers.

The page must not present an empty ontology as ready, and must not offer a form
it will then reject — so the read-only identity gets a ledger with no write
forms at all, and the declared-but-unused types are listed separately from the
smoke leftovers (one is a gap to fill, the other is junk to clean).
"""

from __future__ import annotations

import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import authoring, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

SCHEMA = {
    "entity_types": ["clause", "party", "instrument"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


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
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


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


def _rendered(html: str) -> str:
    """Body only: the i18n catalogue is inlined in a <script>, so a plain
    substring test finds labels that were never rendered."""
    i = html.find("<body")
    body = html[i:] if i >= 0 else html
    return re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def test_units_and_filters_render(conn):
    authoring.authoring_create_unit(conn, domain_key="legal", kind="clause",
                                    external_key="gb-50011", body="防火规范", operator="t")
    authoring.authoring_create_unit(conn, domain_key="legal", kind="party",
                                    external_key="acme", body="甲公司", operator="t")
    with _client(conn, "u-expert") as c:
        page = _rendered(c.get("/d/legal/ontology").text)
        filtered = _rendered(c.get("/d/legal/ontology?kind=party").text)
    # The table lists them; the relation picker lists every live entity on both
    # pages (that is correct — narrowing the list must not narrow the picker).
    assert "<code>gb-50011</code>" in page and "<code>acme</code>" in page
    assert "<code>acme</code>" in filtered
    # `gb-50011` still shows in the recent-events table (it was created), so
    # assert on the unit ROW instead of the bare key.
    assert "<td><code>gb-50011</code></td>" not in filtered
    assert "<td><code>acme</code></td>" in filtered


def test_declared_but_empty_types_are_listed_as_gaps(conn):
    authoring.authoring_create_unit(conn, domain_key="legal", kind="clause",
                                    external_key="k1", body="b", operator="t")
    with _client(conn, "u-expert") as c:
        page = _rendered(c.get("/d/legal/ontology").text)
    # instrument has no instance -> gap section
    assert "声明了但还没有内容" in page
    assert "instrument" in page


def test_smoke_units_are_flagged_separately(conn):
    authoring.authoring_create_unit(conn, domain_key="legal", kind="clause",
                                    external_key="smoke-clause-001", body="冒烟条款", operator="t")
    with _client(conn, "u-expert") as c:
        page = _rendered(c.get("/d/legal/ontology").text)
    assert "疑似测试数据" in page
    assert "smoke-clause-001" in page


def test_annotator_sees_no_write_form(conn):
    with _client(conn, "u-read") as c:
        page = _rendered(c.get("/d/legal/ontology").text)
    assert 'name="external_key"' not in page      # unit form absent
    assert 'name="payload"' not in page           # import form absent
    assert "本体单位" in page or "units" in page  # ledger still there


def test_expert_sees_forms(conn):
    with _client(conn, "u-expert") as c:
        page = _rendered(c.get("/d/legal/ontology").text)
    assert 'name="external_key"' in page
    assert 'name="payload"' in page


def test_events_are_shown_after_a_write(conn):
    authoring.authoring_create_unit(conn, domain_key="legal", kind="clause",
                                    external_key="k-evt", body="b", operator="t")
    with _client(conn, "u-expert") as c:
        page = _rendered(c.get("/d/legal/ontology").text)
    assert "最近变更" in page
    assert "k-evt" in page
