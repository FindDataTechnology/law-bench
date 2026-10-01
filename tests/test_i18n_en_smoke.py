"""EN-locale smoke for the pages migrated by change finish-web-i18n-parity.

Asserts the chrome of previously zh-only destinations actually follows
``?lang=en``: the topbar nav, the page heading, and one per-page chrome string
per destination. Law-catalog pages are excluded here — they need the
law_catalog schema, which only exists in the prod replica, not the per-test
databases.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db


def _user() -> User:
    return User(sub="u1", name="Smoke", email="smoke@example.com", scopes=["*"], channel="test")


@pytest.fixture
def client(seeded_db, monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db

    def _stub_user(request: Request):
        # The template chrome reads request.state.user (see templating), which
        # the real dependency stamps as a side effect — mirror it so the
        # permission-gated nav renders.
        request.state.user = _user()
        return request.state.user

    app.dependency_overrides[get_current_user] = _stub_user
    with TestClient(app) as c:
        yield c


# (path, heading substring, one chrome substring)
EN_DESTINATIONS = [
    ("/dashboard?lang=en", "Contract Evaluation Dashboard", "Pipeline runs"),
    ("/clauses?lang=en", "Clause Library", "Extract from corpus"),
    ("/contracts?lang=en", "Contract Templates", "Pick a contract type"),
    ("/samples?lang=en", "Contract Samples", "All types"),
    ("/search?lang=en", "Semantic Search", "Search backend unavailable"),
    ("/review?lang=en", "Human Review", "Batches"),
]


@pytest.mark.parametrize(("path", "heading", "chrome"), EN_DESTINATIONS)
def test_previously_zh_only_pages_render_english(client, path, heading, chrome):
    page = client.get(path)
    assert page.status_code == 200, f"{path} -> {page.status_code}"
    assert f"<h1>{heading}</h1>" in page.text, f"{path} heading not localized"
    assert chrome in page.text, f"{path} chrome not localized"


def test_nav_is_english_after_switch(client):
    page = client.get("/dashboard?lang=en")
    for label in (">Templates<", ">Samples<", ">Clauses<", ">Dashboard<", ">Review<", ">Search<"):
        assert label in page.text, f"nav label {label} missing"


def test_review_task_page_verdict_labels_follow_locale(seeded_db, client):
    from src.eval import review
    from src.eval.store import store_result

    conn = seeded_db
    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        "VALUES ('contract_smoke_v1', 'contract', 'local', NULL, 'smoke', '2026-01-01T00:00:00+00:00')",
    )
    conn.commit()
    run_id = store_result(
        {
            "rubric": "contract_smoke_v1", "score": 0.0, "max_score": 1.0, "all_pass": 0,
            "n_criteria": 1, "n_passed": 0, "judge_model": "test-judge",
            "criteria_results": [
                {"id": "c1", "title": "criterion", "verdict": "fail", "reasoning": "r"},
            ],
        },
        db_path=conn, draft_text="draft",
    )
    cur = conn.execute(
        "SELECT id FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal", (run_id,)
    )
    rid = cur.fetchone()["id"]
    review.create_batch(batch_id="smoke-en", batch_type="validity", eval_criteria_result_ids=[rid], db=conn)
    task_id = review.list_tasks(batch_id="smoke-en", status="pending", db=conn)[0]["id"]

    zh = client.get(f"/review/{task_id}")
    assert "通过（与标准一致）" in zh.text
    en = client.get(f"/review/{task_id}?lang=en")
    assert "Pass (matches the standard)" in en.text
    assert "(press 1)" in en.text
