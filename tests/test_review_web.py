"""Web tests for the human-review pages (change add-web-human-review).

Covers the spec's access-control, blind-form and decision-flow requirements.
Auth is stubbed through ``dependency_overrides`` except in the anonymous-redirect
test, which deliberately leaves ``get_current_user`` real.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.eval import review
from src.eval.store import store_result
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

RUBRIC = "contract_lease_v3"
MODEL_REASONING = "引用了已废止的合同法第六十条"


def _user(scopes: list[str], email: str = "annotator@example.com") -> User:
    return User(sub="user-1", name="Annotator One", email=email, scopes=scopes, channel="test")


def _seed(conn) -> dict:
    """One rubric+criterion, one eval run, one validity batch of two tasks."""
    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        "VALUES (%s, 'contract', 'local', NULL, 'lease test', '2026-01-01T00:00:00+00:00')",
        (RUBRIC,),
    )
    conn.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'legal_citation_accuracy', '法条引用准确性', "
        "       'PASS 当且仅当所引法条与条文内容一致', 0 FROM rubrics WHERE name = %s",
        (RUBRIC,),
    )
    conn.commit()
    run_id = store_result(
        {
            "rubric": RUBRIC,
            "score": 0.0, "max_score": 1.0, "all_pass": 0,
            "n_criteria": 2, "n_passed": 1, "judge_model": "test-judge",
            "criteria_results": [
                {"id": "legal_citation_accuracy", "title": "法条引用准确性",
                 "verdict": "fail", "reasoning": MODEL_REASONING},
                {"id": "parties", "title": "当事人条款",
                 "verdict": "pass", "reasoning": "当事人信息完整"},
            ],
        },
        db_path=conn,
        draft_text="租赁合同草稿正文：第一条 当事人",
    )
    cur = conn.execute(
        "SELECT id FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal", (run_id,)
    )
    ids = [r["id"] for r in cur.fetchall()]
    review.create_batch(batch_id="web1", batch_type="validity", eval_criteria_result_ids=ids, db=conn)
    review.create_batch(batch_id="web2", batch_type="gold_curation", eval_criteria_result_ids=ids, db=conn)
    return {"run_id": run_id, "result_ids": ids}


def _client(seeded_db, user: User) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def annotator_client(seeded_db, monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    with _client(seeded_db, _user(["*"])) as c:
        yield c


@pytest.fixture
def viewer_client(seeded_db, monkeypatch):
    """Authenticated but without review:annotate."""
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    with _client(seeded_db, _user(["content:read"])) as c:
        yield c


def _first_pending(conn, batch_id: str) -> int:
    return review.list_tasks(batch_id=batch_id, status="pending", db=conn)[0]["id"]


# --- access control -------------------------------------------------------- #


def test_anonymous_navigation_redirects_to_login(seeded_db, monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db  # auth stays real
    with TestClient(app) as c:
        r = c.get("/review", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302
    assert "/auth/login" in r.headers["location"]


def test_viewer_can_open_pages_but_not_decide(seeded_db, viewer_client):
    _seed(seeded_db)
    assert viewer_client.get("/review").status_code == 200

    task_id = _first_pending(seeded_db, "web1")
    assert viewer_client.get(f"/review/{task_id}").status_code == 200

    r = viewer_client.post(f"/review/{task_id}/decide", data={"verdict": "fail"})
    assert r.status_code == 403
    assert review.get_task_detail(task_id, db=seeded_db)["status"] == "pending"


# --- pages ----------------------------------------------------------------- #


def test_review_list_shows_batches(seeded_db, annotator_client):
    _seed(seeded_db)
    r = annotator_client.get("/review")
    assert r.status_code == 200
    assert "web1" in r.text and "web2" in r.text
    assert "效度验证" in r.text and "gold 标注" in r.text


def test_validity_form_is_blind(seeded_db, annotator_client):
    _seed(seeded_db)
    task_id = _first_pending(seeded_db, "web1")
    r = annotator_client.get(f"/review/{task_id}")
    assert r.status_code == 200
    assert "盲评" in r.text
    assert MODEL_REASONING not in r.text          # model reasoning must not leak
    assert "租赁合同草稿正文" in r.text             # draft is shown
    assert "PASS 当且仅当所引法条与条文内容一致" in r.text  # criterion guidance is shown


def test_gold_curation_form_shows_model_verdict(seeded_db, annotator_client):
    _seed(seeded_db)
    task_id = _first_pending(seeded_db, "web2")
    r = annotator_client.get(f"/review/{task_id}")
    assert r.status_code == 200
    assert MODEL_REASONING in r.text
    assert "认可该判定" in r.text and "不认可该判定" in r.text


def test_unknown_task_renders_not_found(seeded_db, annotator_client):
    _seed(seeded_db)
    r = annotator_client.get("/review/999999")
    assert r.status_code == 404
    assert "条目不存在" in r.text


# --- decisions ------------------------------------------------------------- #


def test_decide_records_session_identity(seeded_db, annotator_client):
    _seed(seeded_db)
    task_id = _first_pending(seeded_db, "web1")

    r = annotator_client.post(
        f"/review/{task_id}/decide", data={"verdict": "fail", "note": "法条已废止"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "/review" in r.headers["location"]

    detail = review.get_task_detail(task_id, db=seeded_db)
    assert detail["status"] == "decided"
    assert detail["annotator_verdict"] == "fail"
    assert detail["annotator"] == "annotator@example.com"  # from the session, not the form
    assert detail["note"] == "法条已废止"


def test_decide_conflict_leaves_row_untouched(seeded_db, annotator_client):
    _seed(seeded_db)
    task_id = _first_pending(seeded_db, "web1")
    review.decide_task(task_id=task_id, annotator="someone-else", verdict="pass", db=seeded_db)

    r = annotator_client.post(
        f"/review/{task_id}/decide", data={"verdict": "fail"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert "flash=" in r.headers["location"]
    detail = review.get_task_detail(task_id, db=seeded_db)
    assert detail["annotator"] == "someone-else" and detail["annotator_verdict"] == "pass"


def test_decide_rejects_verdict_not_allowed_for_batch(seeded_db, annotator_client):
    _seed(seeded_db)
    task_id = _first_pending(seeded_db, "web1")
    r = annotator_client.post(f"/review/{task_id}/decide", data={"verdict": "approved"})
    assert r.status_code == 400
    assert review.get_task_detail(task_id, db=seeded_db)["status"] == "pending"


# --- decision-flow continuation (change review-flow-momentum) -------------- #


def _pending_ids(conn, batch_id: str) -> list[int]:
    return [t["id"] for t in review.list_tasks(batch_id=batch_id, status="pending", db=conn)]


def test_decide_redirects_to_next_pending_task(seeded_db, annotator_client):
    _seed(seeded_db)
    ids = _pending_ids(seeded_db, "web1")
    assert len(ids) == 2

    r = annotator_client.post(
        f"/review/{ids[0]}/decide", data={"verdict": "fail"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith(f"/review/{ids[1]}?")
    assert "msg=" in r.headers["location"]
    # The just-decided task is recorded; the next one is still pending.
    assert review.get_task_detail(ids[0], db=seeded_db)["status"] == "decided"
    assert review.get_task_detail(ids[1], db=seeded_db)["status"] == "pending"


def test_decide_queue_drained_redirects_to_batch_list(seeded_db, annotator_client):
    _seed(seeded_db)
    ids = _pending_ids(seeded_db, "web1")
    annotator_client.post(f"/review/{ids[0]}/decide", data={"verdict": "fail"})

    r = annotator_client.post(
        f"/review/{ids[1]}/decide", data={"verdict": "pass"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/review?batch=web1")
    assert "msg=" in r.headers["location"]


def test_pending_task_shows_position_hints_and_primary_submit(seeded_db, annotator_client):
    _seed(seeded_db)
    ids = _pending_ids(seeded_db, "web1")

    page = annotator_client.get(f"/review/{ids[0]}")
    assert page.status_code == 200
    body = page.text
    assert "第 1 / 2 条待判" in body
    assert "（按 1）" in body and "（按 2）" in body
    assert "btn btn-primary" in body
    # The keyboard listener ships only with a pending decision form.
    assert "addEventListener('keydown'" in body


def test_decided_task_has_no_position_indicator_or_form(seeded_db, annotator_client):
    _seed(seeded_db)
    ids = _pending_ids(seeded_db, "web1")
    review.decide_task(task_id=ids[0], annotator="annotator@example.com", verdict="fail", db=seeded_db)

    page = annotator_client.get(f"/review/{ids[0]}")
    assert page.status_code == 200
    assert "条待判</strong>" not in page.text
    assert "（按 1）" not in page.text
    assert "addEventListener('keydown'" not in page.text
