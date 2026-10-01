"""HTML page-flow tests for the evaluation-rules management UI.

Run against a throwaway DB via the ``app_client`` fixture. HTML write flows
redirect (303) with a ``msg`` flash query param; error flows redirect with
``err=1``.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient


def _flash(response) -> tuple[str, bool]:
    q = parse_qs(urlparse(response.headers["location"]).query)
    return q.get("msg", [""])[0], "err" in q


# --- reads ------------------------------------------------------------------ #


def test_index_redirects_to_rubrics(app_client: TestClient):
    r = app_client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/rubrics"


def test_list_rubrics_page(app_client: TestClient):
    r = app_client.get("/rubrics")
    assert r.status_code == 200
    assert "h_rubric" in r.text
    assert "l_rubric" in r.text


def test_rubric_detail_page(app_client: TestClient):
    r = app_client.get("/rubrics/l_rubric")
    assert r.status_code == 200
    assert "c1" in r.text and "c2" in r.text


# --- rubric writes ---------------------------------------------------------- #


def test_create_rubric_form_redirects_with_flash(app_client: TestClient):
    r = app_client.post(
        "/rubrics",
        data={"name": "r_new", "context": "contract", "description": "d"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    _msg, err = _flash(r)
    assert not err
    assert "/rubrics/r_new" in r.headers["location"]


def test_create_rubric_form_error_flash(app_client: TestClient):
    # empty name -> ValidationError -> redirect back with err=1
    r = app_client.post(
        "/rubrics",
        data={"name": "  ", "context": "contract", "description": "d"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    _msg, err = _flash(r)
    assert err


def test_delete_rubric_form(app_client: TestClient):
    app_client.post(
        "/rubrics", data={"name": "r_del", "context": "contract", "description": "d"}
    )
    r = app_client.post("/rubrics/r_del/delete", follow_redirects=False)
    assert r.status_code == 303
    # gone (check via the JSON API, which 404s rather than redirecting)
    assert app_client.get("/api/rubrics/r_del").status_code == 404


# --- criterion writes ------------------------------------------------------- #


def test_add_criterion_form(app_client: TestClient):
    r = app_client.post(
        "/rubrics/l_rubric/criteria",
        data={"name": "c3", "description": "d3", "guidance": "g3"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    detail = app_client.get("/api/rubrics/l_rubric").json()
    assert any(c["name"] == "c3" for c in detail["criteria"])


def test_move_criterion_down(app_client: TestClient):
    detail = app_client.get("/api/rubrics/l_rubric").json()
    cid0 = detail["criteria"][0]["id"]
    r = app_client.post(
        f"/rubrics/l_rubric/criteria/{cid0}/move",
        data={"direction": "down"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    after = app_client.get("/api/rubrics/l_rubric").json()
    assert [c["name"] for c in after["criteria"]] == ["c2", "c1"]


# --- prompts ---------------------------------------------------------------- #


def test_prompts_list_page(app_client: TestClient):
    app_client.post(
        "/api/prompts",
        json={
            "name": "p1",
            "contract_type": "sale",
            "purpose": "drafting",
            "content": "x",
            "description": "d",
        },
    )
    r = app_client.get("/prompts")
    assert r.status_code == 200
    assert "p1" in r.text


def test_create_prompt_form_redirects(app_client: TestClient):
    r = app_client.post(
        "/prompts",
        data={
            "name": "p_form",
            "contract_type": "sale",
            "purpose": "drafting",
            "content": "x",
            "description": "d",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/prompts/p_form" in r.headers["location"]


# --- harbor re-extraction --------------------------------------------------- #


def test_harbor_extract_page_success(app_client: TestClient, monkeypatch):
    from src.web.routes import pages

    monkeypatch.setattr(
        pages, "run_harbor_extraction", lambda db_path=None: (0, "ok", "")
    )
    r = app_client.post("/harbor/extract", follow_redirects=False)
    assert r.status_code == 303
    _msg, err = _flash(r)
    assert not err


def test_harbor_extract_page_failure(app_client: TestClient, monkeypatch):
    from src.web.routes import pages

    monkeypatch.setattr(
        pages, "run_harbor_extraction", lambda db_path=None: (1, "", "boom")
    )
    r = app_client.post("/harbor/extract", follow_redirects=False)
    assert r.status_code == 303
    _msg, err = _flash(r)
    assert err
