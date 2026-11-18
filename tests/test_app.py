"""Tests for ``src/web/app.py``: the app factory, mounts, and the
``ManageError`` -> HTTP-status exception-handler mapping (including the 500
fallback for unmapped ManageErrors).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.eval.errors import ManageError
from src.web.app import STATIC_DIR, TEMPLATES_DIR, create_app


def test_create_app_factory():
    app = create_app()
    assert app.title == "Evaluation Rules Manager"
    client = TestClient(app)
    # docs route registered at the custom path
    assert client.get("/api/docs").status_code == 200
    # static mount present; asset dirs ensured by create_app
    assert any(getattr(r, "path", "") == "/static" for r in app.routes)
    assert STATIC_DIR.is_dir()
    assert TEMPLATES_DIR.is_dir()


def test_error_handlers_map_to_statuses(app_client: TestClient):
    # NotFoundError -> 404
    assert app_client.get("/api/rubrics/__nope__").status_code == 404
    # HarborReadOnlyError -> 403 (update a harbor rubric)
    r = app_client.patch(
        "/api/rubrics/h_rubric",
        json={"name": "h", "context": "check", "description": "d"},
    )
    assert r.status_code == 403
    # ConflictError -> 409 (duplicate local rubric)
    payload = {"name": "dup", "context": "contract", "description": "d", "criteria": []}
    app_client.post("/api/rubrics", json=payload)
    assert app_client.post("/api/rubrics", json=payload).status_code == 409
    # ValidationError -> 400 (empty name)
    r = app_client.post(
        "/api/rubrics",
        json={"name": "   ", "context": "contract", "description": "d", "criteria": []},
    )
    assert r.status_code == 400


def test_unmapped_manage_error_returns_500(app_client: TestClient, monkeypatch):
    # A plain ManageError (not one of the mapped subclasses) hits the 500 fallback.
    from src.eval import manage as M

    def boom(*args, **kwargs):
        raise ManageError("unexpected")

    monkeypatch.setattr(M, "list_rubrics_with_counts", boom)
    r = app_client.get("/api/rubrics")
    assert r.status_code == 500
    assert r.json()["error"] == "unexpected"
