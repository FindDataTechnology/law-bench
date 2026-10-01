"""Web API tests for /api/prompts.

Run against a throwaway DB via the ``app_client`` fixture (which overrides
``get_db``), so the development database is never touched.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

_PREFIX = "__apitest_"


def _name(suffix: str) -> str:
    return f"{_PREFIX}{suffix}"


def _payload(suffix: str, **overrides):
    base = {
        "name": _name(suffix),
        "contract_type": "sale",
        "purpose": "drafting",
        "content": "c",
        "description": "d",
    }
    base.update(overrides)
    return base


def test_list_prompts_json(app_client: TestClient):
    r = app_client.get("/api/prompts")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_get_delete_prompt(app_client: TestClient):
    name = _name("create")
    r = app_client.post("/api/prompts", json=_payload("create", content="hello"))
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == name
    assert body["source"] == "local"

    r = app_client.get(f"/api/prompts/{name}")
    assert r.status_code == 200
    assert r.json()["content"] == "hello"

    r = app_client.delete(f"/api/prompts/{name}")
    assert r.status_code == 200
    assert app_client.get(f"/api/prompts/{name}").status_code == 404


def test_create_conflict_returns_409(app_client: TestClient):
    app_client.post("/api/prompts", json=_payload("conflict"))
    r = app_client.post("/api/prompts", json=_payload("conflict"))
    assert r.status_code == 409


def test_get_unknown_returns_404(app_client: TestClient):
    r = app_client.get("/api/prompts/__apitest_does_not_exist")
    assert r.status_code == 404


def test_validation_error_returns_400(app_client: TestClient):
    # whitespace content -> ValidationError -> 400 (no row created)
    r = app_client.post("/api/prompts", json=_payload("empty", content="   "))
    assert r.status_code == 400


def test_update_prompt(app_client: TestClient):
    created = app_client.post("/api/prompts", json=_payload("upd", content="old")).json()
    r = app_client.patch(
        f"/api/prompts/{created['name']}",
        json=_payload("upd", content="new", contract_type="loan"),
    )
    assert r.status_code == 200
    assert r.json()["content"] == "new"
    assert r.json()["contract_type"] == "loan"
