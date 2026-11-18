"""Batch review (§5): a batch is a unit of work, not a unit of trust.

Confirming a batch still confirms each proposal through the kernel, one by one:
partial failure must be visible, and the ones that succeeded must not be undone.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import proposals, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

SCHEMA = {
    "entity_types": ["clause"],
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
    workspaces.add_member(conn=empty_db, domain_id=dom["id"], user_id="u-lead",
                          role="lead", added_by="t")
    workspaces.add_member(conn=empty_db, domain_id=dom["id"], user_id="u-expert",
                          role="expert", added_by="t")
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


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _submit(conn, key, batch, kind="clause"):
    from src.bench import submitters

    proposals.submit(
        conn, domain_key="legal", source=f"extract:m:{batch}", kind=kind,
        external_key=key, body=key,
        evidence={"chunk_id": "c1", "quote": "q", "batch": batch},
        submitted_by="extraction",
        # These rows stand in for the extraction pipeline, which writes
        # in-process; the external channel rejects ``extract:`` by design.
        via=submitters.VIA_IN_PROCESS,
    )


def test_batches_are_listed_and_filterable(conn):
    _submit(conn, "a1", "batch-one")
    _submit(conn, "b1", "batch-two")
    listed = proposals.batches(conn, domain_key="legal")
    assert {b["batch"] for b in listed} == {"batch-one", "batch-two"}
    only_one = proposals.list_proposals(conn, domain_key="legal", batch="batch-one")
    assert [p["external_key"] for p in only_one] == ["a1"]


def test_batch_confirm_writes_through_the_kernel(conn):
    _submit(conn, "a1", "b1")
    _submit(conn, "a2", "b1")
    with _client(conn, "u-lead") as c:
        r = c.post("/d/legal/inbox/batch", data={"batch": "b1", "action": "confirm"},
                   follow_redirects=False)
    assert r.status_code == 303
    units = conn.execute("SELECT external_key FROM knowledge_units ORDER BY external_key").fetchall()
    assert [u["external_key"] for u in units] == ["a1", "a2"]
    assert conn.execute("SELECT COUNT(*) AS n FROM domain_proposals WHERE state='confirmed'").fetchone()["n"] == 2


def test_partial_failure_does_not_roll_back(conn):
    _submit(conn, "ok1", "b1")
    # 这一行要「确认时失败」，但**提交口现在会拒词表外的 kind**
    # （refuse-out-of-vocabulary-kinds），所以不能再靠 `kind="spaceship"` 提交进来。
    # 那一形态在生产里仍然可达：行在箱里待着的时候模板收窄，或它本身就是加规则之前
    # 就存在的旧行（生产里 #86/#90/#94 正是）。于是按真实成因构造——先合法入箱，
    # 再让世界变化。被测件是批量确认（一条失败不拖垮整批），不是提交口。
    _submit(conn, "bad-kind", "b1")
    conn.execute(
        "UPDATE domain_proposals SET kind = 'spaceship' WHERE external_key = %s",
        ("bad-kind",),
    )
    with _client(conn, "u-lead") as c:
        r = c.post("/d/legal/inbox/batch", data={"batch": "b1", "action": "confirm"},
                   follow_redirects=False)
    assert r.status_code == 303
    units = [u["external_key"] for u in conn.execute("SELECT external_key FROM knowledge_units").fetchall()]
    assert units == ["ok1"], "the succeeding row must stay written"
    assert "failed=1" in r.headers["location"]


def test_expert_cannot_confirm_a_batch(conn):
    _submit(conn, "a1", "b1")
    with _client(conn, "u-expert") as c:
        r = c.post("/d/legal/inbox/batch", data={"batch": "b1", "action": "confirm"},
                   follow_redirects=False)
    assert r.status_code == 403
    assert conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"] == 0


def test_batch_reject_leaves_the_ontology_alone(conn):
    _submit(conn, "a1", "b1")
    with _client(conn, "u-lead") as c:
        r = c.post("/d/legal/inbox/batch", data={"batch": "b1", "action": "reject"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM domain_proposals WHERE state='rejected'").fetchone()["n"] == 1


def test_inbox_page_shows_the_batches(conn):
    _submit(conn, "a1", "batch-visible")
    with _client(conn, "u-lead") as c:
        page = c.get("/d/legal/inbox").text
    assert "batch-visible" in page
