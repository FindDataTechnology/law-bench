"""Promotion machine tests (add-knowledge-bench-platform, P2 组5 柏讯贯通, task A).

Hermetic: a wire-shaped entity graph fixture (2 entities + 1 relation, with
dataset summaries and pk columns — the shape of fd-wire
``GET /api/v1/entities/graph`` per the entity-layer spec) fed through an
injected ``fetch_fn``; no network, no registry client. Covers:

- sync idempotency (double sync adds no rows, bumps nothing);
- sync content-drift handling that never demotes and never erases operator
  annotations;
- bronze→silver→gold full chain; gold requires the reviewer stamp;
- tiers move one adjacent step (no skipping), gold never demotes without an
  explicit forced admin action;
- export_gold payload carries identity key + tier/sensitivity markers;
- run_writeback success records the receipt; a raising channel (network-drop
  style) leaves the unit un-marked, continues the batch, reports honestly;
- rerun writeback skips already-pushed units (registry key = idempotency key);
- minimal route smoke (queue 200, viewer 403, session-identity gold promote,
  body-carried reviewer rejected).

Runs against ``empty_db`` + ``ensure_schema`` (the bench kernel schema), same
posture as tests/test_bench_store.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.bench import promotion, store
from src.bench.promotion import TierTransitionError
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

NAMESPACE = "wire"

#: wire-shaped graph (fd-wire entity-layer spec: nodes carry id/业务名/dataset
#: summary{ id,key,name,row_count,tier }/pk_columns; edges the four-tuple+kind).
GRAPH = {
    "nodes": [
        {
            "id": 1,
            "name": "Customer",
            "description": "the buyer",
            "pk_columns": ["cust_id"],
            "display_column": "cust_name",
            "column_notes": {"cust_id": "opaque surrogate key"},
            "dataset": {
                "id": "ds-1", "key": "customers", "name": "Customers",
                "row_count": 120, "storage_tier": "hot",
            },
        },
        {
            "id": 2,
            "name": "Order",
            "description": None,
            "pk_columns": ["order_id"],
            "display_column": None,
            "column_notes": None,
            "dataset": {
                "id": "ds-2", "key": "orders", "name": "Orders",
                "row_count": 5000, "storage_tier": "hot",
            },
        },
    ],
    "edges": [
        {
            "id": 9,
            "from_entity_id": 2, "from_column": "cust_id",
            "to_entity_id": 1, "to_column": "cust_id",
            "kind": "n:1", "label": "order belongs to customer",
            "junction_dataset_id": None,
            "junction_source_column": None,
            "junction_target_column": None,
        },
    ],
}


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Same posture as test_bench_store: DDL on the fixture's own connection.
    ensure_schema(db_path=empty_db)
    yield empty_db


def _fetch(graph=None):
    g = graph if graph is not None else GRAPH
    return lambda: {"nodes": [dict(n) for n in g["nodes"]],
                    "edges": [dict(e) for e in g["edges"]]}


def _sync(conn) -> dict:
    return promotion.sync_graph(conn, fetch_fn=_fetch(), namespace=NAMESPACE)


def _promote_to_gold(conn, kind, key, reviewer="rev@example.com"):
    promotion.promote_unit(conn, kind=kind, external_key=key,
                           namespace=NAMESPACE, to_tier="silver")
    return promotion.promote_unit(conn, kind=kind, external_key=key,
                                  namespace=NAMESPACE, to_tier="gold",
                                  reviewer=reviewer, note="verified")


def _unit(conn, kind, key):
    return store.get_knowledge_unit(conn, kind=kind, external_key=key,
                                    namespace=NAMESPACE)


# --- sync -------------------------------------------------------------------- #


def test_sync_lands_bronze_and_is_idempotent(db_conn):
    result = _sync(db_conn)
    assert result["created"] == ["1", "2", "9"]
    rows = store.list_knowledge_units(db_conn, namespace=NAMESPACE, limit=100)
    assert len(rows) == 3
    assert all(r["tier"] == "bronze" for r in rows)
    assert all(r["provenance"]["synced_from"] == NAMESPACE for r in rows)
    entities = [_unit(db_conn, "entity", "1"), _unit(db_conn, "entity", "2")]
    assert entities[0]["attrs"]["dataset"]["row_count"] == 120
    assert "pk=[cust_id]" in entities[0]["body"]
    rel = _unit(db_conn, "relation", "9")
    assert "(n:1)" in rel["body"]

    # second sync: no rows added, no writes at all (updated_at untouched)
    before = {r["id"]: r["updated_at"] for r in
              store.list_knowledge_units(db_conn, namespace=NAMESPACE, limit=100)}
    again = _sync(db_conn)
    assert again["created"] == [] and again["updated"] == []
    assert sorted(again["unchanged"]) == ["1", "2", "9"]
    after = {r["id"]: r["updated_at"] for r in
             store.list_knowledge_units(db_conn, namespace=NAMESPACE, limit=100)}
    assert after == before
    assert len(store.list_knowledge_units(db_conn, namespace=NAMESPACE, limit=100)) == 3


def test_sync_content_drift_updates_mirror_without_demoting(db_conn):
    _sync(db_conn)
    promotion.annotate_unit(db_conn, kind="entity", external_key="1",
                            namespace=NAMESPACE, tags={"biz": "crm"},
                            attrs={"owner": "ops"}, reviewer="anno@example.com")
    _promote_to_gold(db_conn, "entity", "1")

    drifted = {
        "nodes": [dict(GRAPH["nodes"][0],
                       dataset=dict(GRAPH["nodes"][0]["dataset"], row_count=130)),
                  GRAPH["nodes"][1]],
        "edges": GRAPH["edges"],
    }
    result = promotion.sync_graph(db_conn, fetch_fn=_fetch(drifted), namespace=NAMESPACE)
    assert result["updated"] == ["1"]

    unit = _unit(db_conn, "entity", "1")
    assert "rows=130" in unit["body"]                    # mirror refreshed
    assert unit["attrs"]["dataset"]["row_count"] == 130
    assert unit["tier"] == "gold"                        # never demoted by sync
    assert unit["tags"]["biz"] == "crm"                  # operator tags survive
    assert unit["provenance"]["annotations"] == {"owner": "ops"}  # attrs survive
    assert unit["provenance"]["review"]["reviewer"] == "rev@example.com"


# --- ladder ------------------------------------------------------------------- #


def test_full_chain_and_gold_requires_reviewer(db_conn):
    _sync(db_conn)
    silver = promotion.promote_unit(db_conn, kind="entity", external_key="1",
                                    namespace=NAMESPACE, to_tier="silver")
    assert silver["tier"] == "silver"

    # gold without a reviewer: refused, unit untouched
    with pytest.raises(ValueError, match="requires a reviewer"):
        promotion.promote_unit(db_conn, kind="entity", external_key="1",
                               namespace=NAMESPACE, to_tier="gold", note="no id")
    assert _unit(db_conn, "entity", "1")["tier"] == "silver"

    gold = promotion.promote_unit(db_conn, kind="entity", external_key="1",
                                  namespace=NAMESPACE, to_tier="gold",
                                  reviewer="rev@example.com", note="checked vs source")
    assert gold["tier"] == "gold"
    review = gold["provenance"]["review"]
    assert review["reviewer"] == "rev@example.com"
    assert review["note"] == "checked vs source"
    assert review["at"]
    assert gold["provenance"]["sensitivity"] == promotion.DEFAULT_SENSITIVITY


def test_steps_are_adjacent_no_skipping(db_conn):
    _sync(db_conn)
    with pytest.raises(TierTransitionError, match="one adjacent step"):
        promotion.promote_unit(db_conn, kind="entity", external_key="1",
                               namespace=NAMESPACE, to_tier="gold",
                               reviewer="rev@example.com")
    with pytest.raises(TierTransitionError, match="already at tier"):
        promotion.promote_unit(db_conn, kind="entity", external_key="1",
                               namespace=NAMESPACE, to_tier="bronze")
    with pytest.raises(TierTransitionError):
        promotion.promote_unit(db_conn, kind="entity", external_key="1",
                               namespace=NAMESPACE, to_tier="raw")


def test_gold_cannot_demote_unless_forced_admin_action(db_conn):
    _sync(db_conn)
    _promote_to_gold(db_conn, "entity", "1")

    with pytest.raises(TierTransitionError, match="demote"):
        promotion.promote_unit(db_conn, kind="entity", external_key="1",
                               namespace=NAMESPACE, to_tier="silver")
    assert _unit(db_conn, "entity", "1")["tier"] == "gold"

    # forced but anonymous demotion is still refused
    with pytest.raises(ValueError, match="reviewer"):
        promotion.promote_unit(db_conn, kind="entity", external_key="1",
                               namespace=NAMESPACE, to_tier="silver", force=True)

    # explicit admin action: force + reviewer, recorded in provenance
    demoted = promotion.promote_unit(db_conn, kind="entity", external_key="1",
                                     namespace=NAMESPACE, to_tier="silver",
                                     force=True, reviewer="admin@example.com",
                                     note="wrong review")
    assert demoted["tier"] == "silver"
    stamp = demoted["provenance"]["demoted"]
    assert stamp["by"] == "admin@example.com" and stamp["from"] == "gold"


# --- export + writeback --------------------------------------------------------- #


def test_export_gold_payload_shape(db_conn):
    _sync(db_conn)
    _promote_to_gold(db_conn, "entity", "1")

    payloads = promotion.export_gold(db_conn, NAMESPACE)
    assert len(payloads) == 1
    p = payloads[0]
    assert p["idempotency_key"] == "wire/entity/1"       # registry key = idempotency
    assert p["external_key"] == "1"                      # identity, no second store
    assert p["kind"] == "entity" and p["tier"] == "gold"
    assert p["sensitivity"] == promotion.DEFAULT_SENSITIVITY
    assert p["registry_fields"]["id"] == 1               # wire-native snapshot
    assert p["registry_fields"]["pk_columns"] == ["cust_id"]
    assert p["review"]["reviewer"] == "rev@example.com"
    assert p["written_back"] is False

    # sensitivity recorded at gold time rides the payload
    _promote_to_gold(db_conn, "relation", "9")
    promotion.promote_unit(db_conn, kind="entity", external_key="2",
                           namespace=NAMESPACE, to_tier="silver")
    promotion.promote_unit(db_conn, kind="entity", external_key="2",
                           namespace=NAMESPACE, to_tier="gold",
                           reviewer="rev2@example.com", sensitivity="confidential")
    p2 = [x for x in promotion.export_gold(db_conn, NAMESPACE)
          if x["external_key"] == "2"][0]
    assert p2["sensitivity"] == "confidential"


def test_writeback_success_records_receipt(db_conn):
    _sync(db_conn)
    _promote_to_gold(db_conn, "entity", "1")
    calls = []

    def fn(payload):
        calls.append(payload)
        return {"status": "updated", "wire_version": 7}

    result = promotion.run_writeback(db_conn, NAMESPACE, fn)
    assert result["counts"] == {"succeeded": 1, "failed": 0, "skipped": 0}
    assert calls[0]["external_key"] == "1"
    unit = _unit(db_conn, "entity", "1")
    prov = unit["provenance"]
    assert prov["written_back"] is True
    assert prov["writeback_receipt"] == {"status": "updated", "wire_version": 7}
    assert prov["writeback_idempotency_key"] == "wire/entity/1"
    assert prov["last_writeback"]["ok"] is True
    # tier untouched
    assert unit["tier"] == "gold"


def test_writeback_failure_not_mistakenly_marked_batch_continues(db_conn):
    _sync(db_conn)
    _promote_to_gold(db_conn, "entity", "1")
    _promote_to_gold(db_conn, "entity", "2")
    _promote_to_gold(db_conn, "relation", "9")

    # "network drop" style: the first push raises, the rest succeed
    def fn(payload):
        if payload["kind"] == "entity" and payload["external_key"] == "1":
            raise ConnectionError("wire unreachable: connection reset")
        return {"ok": True}

    result = promotion.run_writeback(db_conn, NAMESPACE, fn)
    assert result["counts"]["failed"] == 1
    assert result["counts"]["succeeded"] == 2
    assert result["failed"][0]["error"] == "wire unreachable: connection reset"

    bad = _unit(db_conn, "entity", "1")
    assert bad["provenance"].get("written_back") is not True   # NOT marked written
    assert bad["provenance"]["last_writeback"]["ok"] is False
    assert "connection reset" in bad["provenance"]["last_writeback_error"]
    good = _unit(db_conn, "entity", "2")
    assert good["provenance"]["written_back"] is True          # batch continued
    rel = _unit(db_conn, "relation", "9")
    assert rel["provenance"]["written_back"] is True


def test_writeback_rerun_is_idempotent(db_conn):
    _sync(db_conn)
    _promote_to_gold(db_conn, "entity", "1")
    calls = []

    def fn(payload):
        calls.append(payload["idempotency_key"])
        return {"receipt": 1}

    r1 = promotion.run_writeback(db_conn, NAMESPACE, fn)
    assert r1["counts"]["succeeded"] == 1
    r2 = promotion.run_writeback(db_conn, NAMESPACE, fn)
    # no second push => no duplicate rows upstream; honest skip reported
    assert r2["counts"] == {"succeeded": 0, "failed": 0, "skipped": 1}
    assert len(calls) == 1
    assert r2["skipped"][0]["external_key"] == "1"
    # force re-sends (payload still carries the idempotency key)
    r3 = promotion.run_writeback(db_conn, NAMESPACE, fn, force=True)
    assert r3["counts"]["succeeded"] == 1
    assert calls == ["wire/entity/1", "wire/entity/1"]


# --- route smoke (review-web style) ------------------------------------------------ #


def _user(scopes: list[str], email: str = "annotator@example.com") -> User:
    return User(sub="user-1", name="Annotator One", email=email, scopes=scopes,
                channel="test")


def _client(conn, user: User, monkeypatch) -> TestClient:
    """TestClient without lifespan: the app's startup events warm caches via a
    process-wide shared connection (``_load_tag_vocab``), which would pin the
    per-test ``empty_db`` database against the fixture's DROP at teardown. The
    auth dependency is overridden below, so the startup checks are not needed
    for these route tests."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    return TestClient(app)


def test_queue_view_200_viewer_cannot_promote_403(db_conn, monkeypatch):
    _sync(db_conn)
    c = _client(db_conn, _user(["content:read"]), monkeypatch)
    r = c.get("/promotion/queue", params={"namespace": NAMESPACE})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    kinds = {tuple((c0["namespace"], c0["kind"], c0["tier"], c0["n"]))
             for c0 in body["counts"]}
    assert ("wire", "entity", "bronze", 2) in kinds
    assert ("wire", "relation", "bronze", 1) in kinds
    # authenticated but no review scope -> write ops 403, queue untouched
    r = c.post("/promotion/units/entity/1/promote",
               json={"namespace": NAMESPACE, "to_tier": "silver"})
    assert r.status_code == 403
    assert _unit(db_conn, "entity", "1")["tier"] == "bronze"


def test_promote_uses_session_identity_and_writeback_degrades_honestly(db_conn, monkeypatch):
    _sync(db_conn)
    c = _client(db_conn, _user(["*"]), monkeypatch)
    # bronze -> silver
    r = c.post("/promotion/units/entity/1/promote",
               json={"namespace": NAMESPACE, "to_tier": "silver", "note": "tagged"})
    assert r.status_code == 200
    # a body-carried reviewer is rejected outright (session-only discipline)
    r = c.post("/promotion/units/entity/1/promote",
               json={"namespace": NAMESPACE, "to_tier": "gold",
                     "reviewer": "someone-else"})
    assert r.status_code == 400
    # silver -> gold: reviewer = session identity
    r = c.post("/promotion/units/entity/1/promote",
               json={"namespace": NAMESPACE, "to_tier": "gold",
                     "note": "checked vs wire source"})
    assert r.status_code == 200
    prov = r.json()["provenance"]
    assert prov["review"]["reviewer"] == "annotator@example.com"

    # illegal move -> 409
    r = c.post("/promotion/units/entity/1/promote",
               json={"namespace": NAMESPACE, "to_tier": "bronze"})
    assert r.status_code == 409

    # writeback without a registered channel: honest failure, no false mark
    r = c.post("/promotion/writeback", json={"namespace": NAMESPACE})
    assert r.status_code == 200
    out = r.json()
    assert out["counts"] == {"succeeded": 0, "failed": 1, "skipped": 0}
    assert "no registry writeback channel" in out["failed"][0]["error"]
    assert _unit(db_conn, "entity", "1")["provenance"].get("written_back") is not True

    # queue decorates state for the page
    r = c.get("/promotion/queue", params={"namespace": NAMESPACE, "tier": "gold"})
    assert r.status_code == 200
    row = r.json()["units"][0]
    assert row["external_key"] == "1" and row["tier"] == "gold"
    assert row["reviewer"] == "annotator@example.com"
    assert row["written_back"] is False
