#!/usr/bin/env python3
"""Offline self-check for the wire-connector (internal repo has no pytest).

Run from anywhere with a bare python3 (no venv, no network):

    python3 wire-connector/selfcheck.py

Checks (all hermetic):
 1. package imports (client/sync/writeback load with stdlib only —
    ``requests``/``psycopg`` are lazy, so a missing package is reported as
    environment info, not a crash);
 2. public-kernel import through the LAW_BENCH_REPO wiring (VAAS precedent:
    internal → public only);
 3. pure promotion functions produce wire-shaped mirrors;
 4. client constructs with env/params and the no-credentials path raises an
    honest, actionable WireAuthError BEFORE any network touch;
 5. writeback stamp formatting carries tier/sensitivity/idempotency markers.

Prints 'OK <check>' per check; exits 1 with the failing check on any problem.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # .../wire-connector


def _fail(check: str, err: Exception) -> None:
    print(f"FAIL {check}: {type(err).__name__}: {err}")
    sys.exit(1)


def main() -> int:
    src = HERE / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    # 1. package imports (stdlib-only by design: lazy requests/psycopg)
    try:
        import wire_connector  # noqa: F401
        from wire_connector import client as _c, sync as _s, writeback as _w
    except Exception as e:  # noqa: BLE001
        _fail("wire_connector import", e)
    print("OK 1 wire_connector imports (client/sync/writeback)")

    # 2. public kernel through the cross-repo wiring
    try:
        promotion = _s.import_kernel()
        assert hasattr(promotion, "sync_graph")
        assert hasattr(promotion, "run_writeback")
        assert hasattr(promotion, "export_gold")
    except Exception as e:  # noqa: BLE001
        _fail("law-bench kernel import (set LAW_BENCH_REPO?)", e)
    print(f"OK 2 public kernel promotion module: {promotion.__file__}")

    # 3. pure mirror rendering (wire graph shape, fixture — no DB, no network)
    node = {
        "id": 1, "name": "Customer", "description": None,
        "pk_columns": ["cust_id"], "display_column": None, "column_notes": None,
        "dataset": {"id": "ds-1", "key": "customers", "name": "Customers",
                    "row_count": 120, "storage_tier": "hot"},
    }
    edge = {"id": 9, "from_entity_id": 2, "from_column": "cust_id",
            "to_entity_id": 1, "to_column": "cust_id", "kind": "n:1",
            "label": None, "junction_dataset_id": None,
            "junction_source_column": None, "junction_target_column": None}
    try:
        body = promotion.render_entity_body(node)
        assert "pk=[cust_id]" in body and "rows=120" in body, body
        rel = promotion.render_relation_body(edge)
        assert "(n:1)" in rel, rel
        assert promotion.entity_external_key(node) == "1"
        assert promotion.relation_external_key(edge) == "9"
    except Exception as e:  # noqa: BLE001
        _fail("mirror rendering", e)
    print("OK 3 wire-shaped node/edge render into unit bodies/keys")

    # 4. client: constructs; dual-mode routing; no-credential paths raise
    #    honestly, pre-network (task 1.1)
    try:
        c = _c.WireClient(base_url="http://wire.invalid", id_token="fake")
        assert c._headers(machine=False)["Authorization"] == "Bearer fake"
        # repr never leaks tokens (task 1.4)
        r = repr(c)
        assert "fake" not in r and "<set:" in r, r
        # machine-only client: read routes to the internal mirror shape
        m = _c.WireClient(base_url="http://wire.invalid",
                          internal_token="mt", customer_id="cust-1")
        assert m.machine_reads_available
        # write face still demands console token (never machine-mode writes)
        try:
            m._require_write_credentials()
            raise AssertionError("expected WireAuthError without console token")
        except _c.WireAuthError as e:
            assert "WIRE_ID_TOKEN" in str(e) and "machine" in str(e).lower(), e
        # no credentials at all: read face raises actionable error pre-network
        noauth = _c.WireClient(base_url="http://wire.invalid")
        try:
            noauth.get_graph()
            raise AssertionError("expected WireAuthError with no credentials")
        except _c.WireAuthError as e:
            assert "WIRE_INTERNAL_TOKEN" in str(e) and "WIRE_ID_TOKEN" in str(e), e
        naked = _c.WireClient(base_url="", id_token="x")
        try:
            naked.get_graph()
            raise AssertionError("expected WireClientError with no base")
        except _c.WireClientError as e:
            assert "WIRE_API_BASE" in str(e), e
    except Exception as e:  # noqa: BLE001
        _fail("client dual-mode / no-credential error path", e)
    print("OK 4 client dual-mode routing; no-cred paths raise actionable errors pre-network; repr masked")

    # 5. writeback stamp markers (tier/sensitivity/idempotency on the payload)
    try:
        payload = {
            "kind": "entity", "external_key": "1", "tier": "gold",
            "sensitivity": "confidential", "idempotency_key": "wire/entity/1",
            "review": {"reviewer": "rev@x.com", "at": "2026-11-03T00:00:00+00:00"},
            "registry_fields": node,
        }
        stamp = _w.format_bench_stamp(payload)
        for marker in ("tier=gold", "sensitivity=confidential",
                       "idempotency_key=wire/entity/1", "reviewer=rev@x.com"):
            assert marker in stamp, (marker, stamp)
    except Exception as e:  # noqa: BLE001
        _fail("writeback stamp markers", e)
    print(f"OK 5 gold writeback stamp: {stamp}")

    # 5b. 0050 first-class surfaces: entity PUT body carries tier/sensitivity;
    #     relation update goes through the PUT update face (no more refusal)
    try:
        captured = {}

        class _FakeClient:
            def update_entity(self, entity_id, **kw):
                captured["entity"] = (entity_id, kw)
                return {"updated_at": "2026-11-05T00:00:00"}
            def update_relationship(self, entity_id, rel_id, **kw):
                captured["relation"] = (entity_id, rel_id, kw)
                return {"label": kw.get("label")}

        wb = _w.WireWriteback(_FakeClient())
        node_payload = {
            "kind": "entity", "external_key": "7", "tier": "gold",
            "sensitivity": "confidential", "idempotency_key": "wire/entity/7",
            "review": {"reviewer": "r@x", "at": "2026-11-05T00:00:00"},
            "registry_fields": dict(node),
        }
        receipt = wb(node_payload)
        eid, kw = captured["entity"]
        assert eid == 7 and kw["tier"] == "gold" and kw["sensitivity"] == "confidential", kw
        assert "_bench" in (kw.get("column_notes") or {}), kw  # bag rides along
        assert receipt["endpoint"].startswith("PUT /api/v1/entities/7"), receipt

        edge_payload = {
            "kind": "relation", "external_key": "9", "tier": "gold",
            "sensitivity": "internal", "idempotency_key": "wire/relation/9",
            "review": {"reviewer": "r@x"},
            "registry_fields": dict(edge),
        }
        receipt = wb(edge_payload)
        feid, rid, kw = captured["relation"]
        assert (feid, rid) == (2, 9), (feid, rid)
        assert kw == {"label": None, "tier": "gold", "sensitivity": "internal"}, kw
        assert "relationships/" in receipt["endpoint"], receipt
    except Exception as e:  # noqa: BLE001
        _fail("0050 first-class writeback surfaces", e)
    print("OK 5b entity PUT carries first-class tier/sensitivity; relation via update face")

    # 5c. batch confirmation gate (task 1.2): unconfirmed -> zero writes
    try:
        calls = []

        class _NoWriteClient:
            def update_entity(self, *a, **kw):
                calls.append(("entity", a, kw))
                return {}
            def update_relationship(self, *a, **kw):
                calls.append(("relation", a, kw))
                return {}

        gold_payload = {
            "idempotency_key": "wire/entity/1", "registry_namespace": "wire",
            "kind": "entity", "external_key": "1", "tier": "gold",
            "sensitivity": "internal", "registry_fields": dict(node),
            "review": {"reviewer": "r@x"}, "written_back": False,
        }

        class _FakeKernel:
            """Minimal stand-in for the imported kernel (avoid PG in selfcheck)."""
            @staticmethod
            def export_gold(conn, namespace, limit=1000):
                return [dict(gold_payload)]
            @staticmethod
            def run_writeback(conn, namespace, writeback_fn, force=False, limit=1000):
                # only called after confirmation; record the push
                writeback_fn(gold_payload)
                return {"succeeded": [gold_payload["idempotency_key"]], "failed": [], "skipped": [], "counts": {}}

        import wire_connector.writeback as wbmod
        original_loader = wbmod._kernel_loader
        wbmod._kernel_loader = lambda: _FakeKernel
        try:
            dry = wbmod.run_writeback_confirmed(None, "wire", _NoWriteClient(), dry_run=True)
            assert dry["pushed"] is False and dry["confirmed"] is None and "1 unit" in dry["preview"], dry
            denied = wbmod.run_writeback_confirmed(None, "wire", _NoWriteClient(), confirm=lambda b: False)
            assert denied["confirmed"] is False and denied["pushed"] is False and not calls, (denied, calls)
            ok = wbmod.run_writeback_confirmed(None, "wire", _NoWriteClient(), confirm=lambda b: True)
            assert ok["confirmed"] is True and ok["pushed"] is True and len(calls) == 1, (ok, calls)
        finally:
            wbmod._kernel_loader = original_loader
    except Exception as e:  # noqa: BLE001
        _fail("batch confirmation gate", e)
    print("OK 5c run_writeback_confirmed: dry-run/denied/approved paths, zero writes before confirm")

    # environment info (not pass/fail)
    try:
        import requests  # noqa: F401
        print("INFO live-call dependency 'requests' is installed")
    except ImportError:
        print("INFO 'requests' absent in this interpreter — live sync/writeback "
              "will report it honestly when run inside a venv that has it")
    print("INFO WIRE_API_BASE=%s WIRE_ID_TOKEN=%s BENCH_DATABASE_URL=%s LAW_BENCH_REPO=%s" % (
        os.environ.get("WIRE_API_BASE", "(unset)"),
        "set" if os.environ.get("WIRE_ID_TOKEN") else "(unset)",
        os.environ.get("BENCH_DATABASE_URL") or os.environ.get("database_url") or "(unset)",
        os.environ.get("LAW_BENCH_REPO", "(inferred sibling)"),
    ))
    print("\nALL SELFCHECKS PASSED (offline; no network touched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
