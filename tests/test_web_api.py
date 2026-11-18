"""Web API tests for /api/rubrics and /api/rubrics/{name}/criteria.

Run against a throwaway DB via the ``app_client`` fixture (``get_db``
overridden), so the development database is never touched. Each test starts
with one harbor rubric (``h_rubric``, read-only) and one local rubric
(``l_rubric`` with criteria ``c1``, ``c2``).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


# --- rubric reads ----------------------------------------------------------- #


def test_list_rubrics_json(app_client: TestClient):
    r = app_client.get("/api/rubrics")
    assert r.status_code == 200
    names = {rb["name"] for rb in r.json()}
    assert {"h_rubric", "l_rubric"} <= names


def test_get_rubric_detail(app_client: TestClient):
    r = app_client.get("/api/rubrics/l_rubric")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "l_rubric"
    assert body["is_harbor"] is False
    assert [c["name"] for c in body["criteria"]] == ["c1", "c2"]


def test_get_unknown_rubric_404(app_client: TestClient):
    assert app_client.get("/api/rubrics/nope").status_code == 404


# --- rubric writes ---------------------------------------------------------- #


def _rubric_payload(suffix: str, **overrides) -> dict:
    base = {
        "name": f"r_{suffix}",
        "context": "contract",
        "description": "d",
        "criteria": [{"name": "x", "description": "dx", "guidance": "gx"}],
    }
    base.update(overrides)
    return base


def test_create_rubric_with_criteria(app_client: TestClient):
    r = app_client.post("/api/rubrics", json=_rubric_payload("new"))
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "r_new"
    assert body["source"] == "local"
    assert body["criterion_count"] == 1


def test_create_rubric_conflict_409(app_client: TestClient):
    app_client.post("/api/rubrics", json=_rubric_payload("dup"))
    r = app_client.post("/api/rubrics", json=_rubric_payload("dup"))
    assert r.status_code == 409


def test_create_rubric_validation_400(app_client: TestClient):
    # empty name -> ValidationError -> 400
    r = app_client.post("/api/rubrics", json=_rubric_payload("x", name="   "))
    assert r.status_code == 400


def test_update_rubric(app_client: TestClient):
    app_client.post("/api/rubrics", json=_rubric_payload("upd"))
    r = app_client.patch(
        "/api/rubrics/r_upd",
        json={"name": "r_upd2", "context": "check", "description": "d2"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "r_upd2"
    assert r.json()["context"] == "check"


def test_update_harbor_rubric_403(app_client: TestClient):
    r = app_client.patch(
        "/api/rubrics/h_rubric",
        json={"name": "h", "context": "check", "description": "d"},
    )
    assert r.status_code == 403


def test_delete_rubric(app_client: TestClient):
    app_client.post("/api/rubrics", json=_rubric_payload("del"))
    r = app_client.delete("/api/rubrics/r_del")
    assert r.status_code == 200
    assert app_client.get("/api/rubrics/r_del").status_code == 404


def test_delete_harbor_rubric_403(app_client: TestClient):
    assert app_client.delete("/api/rubrics/h_rubric").status_code == 403


# --- criterion writes ------------------------------------------------------- #


def test_add_criterion(app_client: TestClient):
    r = app_client.post(
        "/api/rubrics/l_rubric/criteria",
        json={"name": "c3", "description": "d3", "guidance": "g3"},
    )
    assert r.status_code == 201
    assert r.json()["ordinal"] == 2
    detail = app_client.get("/api/rubrics/l_rubric").json()
    assert [c["name"] for c in detail["criteria"]] == ["c1", "c2", "c3"]


def test_add_criterion_to_harbor_403(app_client: TestClient):
    r = app_client.post(
        "/api/rubrics/h_rubric/criteria",
        json={"name": "x", "description": "d", "guidance": "g"},
    )
    assert r.status_code == 403


def test_add_duplicate_criterion_409(app_client: TestClient):
    r = app_client.post(
        "/api/rubrics/l_rubric/criteria",
        json={"name": "c1", "description": "d", "guidance": "g"},
    )
    assert r.status_code == 409


def test_update_criterion(app_client: TestClient):
    detail = app_client.get("/api/rubrics/l_rubric").json()
    cid = detail["criteria"][0]["id"]
    r = app_client.patch(
        f"/api/rubrics/l_rubric/criteria/{cid}",
        json={"name": "c1r", "description": "d", "guidance": "g"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "c1r"


def test_delete_criterion_renumbers(app_client: TestClient):
    detail = app_client.get("/api/rubrics/l_rubric").json()
    cid0 = detail["criteria"][0]["id"]
    r = app_client.delete(f"/api/rubrics/l_rubric/criteria/{cid0}")
    assert r.status_code == 200
    after = app_client.get("/api/rubrics/l_rubric").json()
    assert [c["name"] for c in after["criteria"]] == ["c2"]
    assert after["criteria"][0]["ordinal"] == 0


def test_reorder_criteria(app_client: TestClient):
    detail = app_client.get("/api/rubrics/l_rubric").json()
    ids = [c["id"] for c in detail["criteria"]]
    r = app_client.post(
        "/api/rubrics/l_rubric/criteria/reorder",
        json={"ordered_criterion_ids": list(reversed(ids))},
    )
    assert r.status_code == 200
    after = app_client.get("/api/rubrics/l_rubric").json()
    assert [c["name"] for c in after["criteria"]] == ["c2", "c1"]


def test_reorder_wrong_id_set_400(app_client: TestClient):
    detail = app_client.get("/api/rubrics/l_rubric").json()
    ids = [c["id"] for c in detail["criteria"]]
    # pass only one of the two ids -> ValidationError -> 400
    r = app_client.post(
        "/api/rubrics/l_rubric/criteria/reorder",
        json={"ordered_criterion_ids": [ids[0]]},
    )
    assert r.status_code == 400
