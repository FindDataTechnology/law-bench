"""The eval-runs page must not present a dead lane as "nothing evaluated yet"."""

from __future__ import annotations

import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

SCHEMA = {
    "entity_types": ["clause"], "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites"], "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    # rubrics/criteria/prompts come from a legacy seed script, not ensure_schema;
    # the eval-assets shelf joins them.
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS rubrics (id BIGINT GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, name TEXT NOT NULL, context TEXT, source TEXT, source_path TEXT, "
        "description TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS criteria (id BIGINT GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, rubric_id BIGINT NOT NULL, name TEXT NOT NULL, description TEXT, "
        "guidance TEXT, ordinal INTEGER NOT NULL DEFAULT 0)"
    )
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS prompts (id BIGINT GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, name TEXT NOT NULL, prompt_type TEXT, content TEXT, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.commit()
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    dom = workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    for role, sub in (("lead", "u-lead"), ("annotator", "u-read")):
        workspaces.add_member(conn=empty_db, domain_id=dom["id"], user_id=sub,
                              role=role, added_by="t")
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _client(db, sub):
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
    i = html.find("<body")
    body = html[i:] if i >= 0 else html
    return re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def test_page_shows_missing_configuration(conn, monkeypatch):
    """Render the *unconfigured* state directly.

    Clearing env vars does not work here: `src.settings` calls `load_dotenv()` at
    import time, so the process environment already carries OPENAI_* from the
    local `.env`. What this test owns is the template's rendering of the state —
    the describe() semantics are covered in test_lane_health.
    """
    from src.bench import lane as lane_mod

    monkeypatch.setattr(lane_mod, "describe", lambda env=None: {
        "configured": False, "base": None, "model": None, "missing": ["key"],
    })
    with _client(conn, "u-lead") as c:
        page = _rendered(c.get("/d/legal/eval-runs").text)
    assert "模型通道" in page
    assert "未配置" in page


def test_page_shows_configured_lane(conn, monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE", "https://x/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("EVAL_MODEL", "openai/deepseek-v4-flash")
    with _client(conn, "u-lead") as c:
        page = _rendered(c.get("/d/legal/eval-runs").text)
    assert "deepseek-v4-flash" in page


def test_probe_is_lead_only(conn, monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE", "https://x/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("EVAL_MODEL", "openai/m")
    from src.bench import lane as lane_mod

    monkeypatch.setattr(lane_mod, "_probe_post",
                        lambda *a, **kw: type("R", (), {"status_code": 200, "text": ""})())
    with _client(conn, "u-read") as c:
        denied = c.post("/d/legal/eval-runs/lane-probe", follow_redirects=False)
    assert denied.status_code == 403

    with _client(conn, "u-lead") as c:
        ok = c.post("/d/legal/eval-runs/lane-probe", follow_redirects=False)
    assert ok.status_code == 303
    assert "lane_probe" in ok.headers["location"]
