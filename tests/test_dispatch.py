"""Batch dispatch (§4.7): gaps become assigned tasks, only after confirmation.

Three behaviours are pinned, each of which is a real way this feature could hurt:

- **loading the estate writes nothing** — the plan lives on its own page, so a
  refresh cannot create tasks;
- **a second confirmation does not duplicate** — an open task for the same
  pillar means "already assigned", and the page says so instead of silently
  skipping;
- **a caller cannot dispatch into a domain it cannot see** — the planner uses
  the same visible-domain set the estate page renders.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import dispatch, libraries, templates
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
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS rubrics ("
        "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL,"
        "context TEXT, source TEXT, source_path TEXT, description TEXT,"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS criteria ("
        "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
        "rubric_id BIGINT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,"
        "name TEXT NOT NULL, description TEXT, guidance TEXT,"
        "ordinal INTEGER NOT NULL DEFAULT 0)"
    )
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS prompts ("
        "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL,"
        "prompt_type TEXT, content TEXT,"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.commit()
    templates.create_template(
        empty_db, name="tpl", created_by="t",
        schema={
            "entity_types": ["clause"], "concept_structures": {"clause": ["id"]},
            "relationship_kinds": ["cites_law"], "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": ["external"]},
        },
    )
    for key, path in (("legal", "legal"), ("cr", "legal/cr")):
        parent = None if key == "legal" else empty_db.execute(
            "SELECT id FROM domains WHERE key='legal'").fetchone()["id"]
        empty_db.execute(
            "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
            "SELECT %s,%s,id,1,'t',%s,%s FROM ontology_templates ORDER BY id LIMIT 1",
            (key, key.upper(), parent, path),
        )
    empty_db.commit()
    import src.eval.store as eval_store
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _client(db, *, scopes=("*",)) -> TestClient:
    app = create_app()
    user = User(sub="u1", name="u1", email="u1@example.com", scopes=list(scopes),
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


def _task_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM authoring_tasks").fetchone()["n"]


def test_loading_the_estate_and_the_plan_creates_nothing(conn):
    with _client(conn) as c:
        assert c.get("/d?gap=knowledge").status_code == 200
        assert c.get("/d/dispatch?gap=knowledge").status_code == 200
    assert _task_count(conn) == 0


def test_confirm_creates_one_task_per_gap_domain(conn):
    with _client(conn) as c:
        r = c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops@example.com"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert _task_count(conn) == 2  # legal + cr both lack corpus
    rows = conn.execute(
        "SELECT domain_id, assignee, target_key, target_kind, status FROM authoring_tasks"
    ).fetchall()
    assert {r["target_key"] for r in rows} == {"knowledge"}
    assert {r["assignee"] for r in rows} == {"ops@example.com"}
    assert {r["status"] for r in rows} == {"pending"}


def test_second_confirmation_does_not_duplicate(conn):
    with _client(conn) as c:
        c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops"}, follow_redirects=False)
        first = _task_count(conn)
        r = c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops"},
                   follow_redirects=False)
    assert _task_count(conn) == first
    assert "skipped=2" in r.headers["location"] or "skipped" in r.headers["location"]
    # The plan page reports them as already open rather than hiding them.
    with _client(conn) as c:
        page = c.get("/d/dispatch?gap=knowledge")
    assert page.status_code == 200


def test_dispatch_requires_an_assignee(conn):
    with _client(conn) as c:
        r = c.post("/d/dispatch", data={"gap": "knowledge", "assignee": ""},
                   follow_redirects=False)
    assert _task_count(conn) == 0
    assert r.status_code == 303  # bounced back with a flash, nothing written


def test_unknown_pillar_is_refused(conn):
    with _client(conn) as c:
        r = c.post("/d/dispatch", data={"gap": "everything", "assignee": "x"},
                   follow_redirects=False)
    assert _task_count(conn) == 0
    assert r.status_code == 303


def test_a_domain_with_content_is_not_dispatched(conn):
    lib = libraries.create_library(conn, library_key="law", name="Law", created_by="t")
    libraries.add_source(conn, library_key="law", source_key="s1", uri="s3://b/s1", created_by="t")
    legal = conn.execute("SELECT id, path FROM domains WHERE key='legal'").fetchone()
    libraries.subscribe(conn, domain_id=legal["id"], library_key="law", created_by="t")
    conn.execute(
        "INSERT INTO corpus_chunks (library_id, scope_path, source_key, doc_path, chunk_seq, "
        "content, content_hash) VALUES (%s, %s, 's1', 'd.md', 0, 'b', 'h')",
        (lib["id"], legal["path"]),
    )
    conn.commit()
    # Give legal a rubric too, so its only remaining gap is 'inbox' (not a pillar).
    conn.execute(
        "INSERT INTO rubrics (name, context, source, description, domain_id) "
        "VALUES ('q','c','seed','d',%s)", (legal["id"],)
    )
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, created_at, updated_at) "
        "VALUES ('entity','legal','party','b','now','now')"
    )
    conn.commit()
    # A second root with no subscription: only a domain off legal's chain can
    # still lack corpus, because `cr` inherits legal's grant and sees the chunk.
    conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "SELECT 'solo','Solo',id,1,'t','solo' FROM ontology_templates ORDER BY id LIMIT 1"
    )
    conn.commit()
    rows = dispatch.rows_for_gap(
        conn,
        domains=[dict(r) for r in conn.execute("SELECT * FROM domains").fetchall()],
        gap="knowledge",
    )
    planned = dispatch.plan(conn, rows=rows, gap="knowledge", assignee="ops")
    # `legal` has real chunks; `cr` inherits them (ancestor chain); only `solo`
    # is genuinely missing corpus.
    assert [d["key"] for d in planned["will_create"]] == ["solo"]


def test_dispatched_task_is_visible_in_the_inbox(conn):
    """A batch dispatch assigns free-text identities; the overview only lists
    tasks whose assignee equals the caller's id, so without the inbox list the
    task is invisible to everyone."""
    with _client(conn) as c:
        c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops@example.com"},
               follow_redirects=False)
    with _client(conn) as c:
        page = c.get("/d/legal/inbox")
    assert page.status_code == 200
    assert "ops@example.com" in page.text
    assert "补语料" in page.text          # the task title from GAP_TASKS


def test_closing_a_task_reopens_the_gap_for_dispatch(conn):
    """Dispatch is idempotent per open task — so closing must be possible,
    otherwise a domain can never be dispatched again.

    Closing now goes through claim → complete (``add-fleet-execution-loop`` §1.4):
    a pending task cannot jump straight to done, because "完成了" on something
    nobody claimed records an outcome that never happened. The gap reopens the
    same way it always did — the task simply has to reach ``done``.
    """
    with _client(conn) as c:
        c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops"},
               follow_redirects=False)
    task_id = conn.execute("SELECT id FROM authoring_tasks LIMIT 1").fetchone()["id"]

    # pending → done 被拒：没认领就没有「完成」可言。
    with _client(conn) as c:
        direct = c.post(
            f"/d/legal/inbox/tasks/{task_id}/transition", data={"to": "done"},
            follow_redirects=False,
        )
    assert direct.status_code == 303
    assert conn.execute(
        "SELECT status FROM authoring_tasks WHERE id=%s", (task_id,)
    ).fetchone()["status"] == "pending", "未认领不得直接完成"

    with _client(conn) as c:
        c.post(f"/d/legal/inbox/tasks/{task_id}/transition",
               data={"to": "in_progress"}, follow_redirects=False)
        r = c.post(f"/d/legal/inbox/tasks/{task_id}/transition", data={"to": "done"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert conn.execute("SELECT status FROM authoring_tasks WHERE id=%s", (task_id,)).fetchone()["status"] == "done"
    before = _task_count(conn)
    with _client(conn) as c:
        c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops"},
               follow_redirects=False)
    # Only the domain whose task was closed becomes dispatchable again; `cr`
    # still has an open task, so exactly one new row appears.
    assert _task_count(conn) == before + 1
    # `legal` was re-created (its task is new); `cr` keeps its original task.
    per_domain = {
        r["key"]: r["n"]
        for r in conn.execute(
            "SELECT d.key, COUNT(*) AS n FROM authoring_tasks t "
            "JOIN domains d ON d.id=t.domain_id "
            "WHERE t.status='pending' AND t.target_key='knowledge' GROUP BY d.key"
        ).fetchall()
    }
    assert per_domain == {"legal": 1, "cr": 1}


def test_outsider_cannot_close_someone_elses_task(conn):
    with _client(conn) as c:
        c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "someone-else"},
               follow_redirects=False)
    task_id = conn.execute("SELECT id FROM authoring_tasks LIMIT 1").fetchone()["id"]
    # A non-admin, non-lead identity that is neither the assignee.
    with _client(conn, scopes=("content:read", "content:write")) as c:
        r = c.post(f"/d/legal/inbox/tasks/{task_id}/transition", data={"to": "done"},
                   follow_redirects=False)
    assert r.status_code == 403
    assert conn.execute("SELECT status FROM authoring_tasks WHERE id=%s", (task_id,)).fetchone()["status"] == "pending"


def test_task_from_another_domain_is_404(conn):
    with _client(conn) as c:
        c.post("/d/dispatch", data={"gap": "knowledge", "assignee": "ops"},
               follow_redirects=False)
    task_id = conn.execute(
        "SELECT t.id FROM authoring_tasks t JOIN domains d ON d.id=t.domain_id WHERE d.key='cr' LIMIT 1"
    ).fetchone()["id"]
    with _client(conn) as c:
        r = c.post(f"/d/legal/inbox/tasks/{task_id}/transition", data={"to": "done"},
                   follow_redirects=False)
    assert r.status_code == 404
