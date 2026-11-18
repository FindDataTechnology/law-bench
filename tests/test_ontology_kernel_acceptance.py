"""End-to-end acceptance for the kernel-backed authoring surface (task 5.7).

One flow, in the order a domain actually goes through it:

    seed content → publish v1 → publish again (idempotent) → bulk import →
    re-import (updates) → publish v2 → ledger + reconcile

plus one extraction batch driven by a **stub completer**. The model is not what
changed in this refactor; the gates, the counters and the proposal inbox are.
Using a stub keeps the acceptance deterministic while still exercising prompt
building, candidate parsing, verbatim-quote verification, the key gates and the
proposal write.

The run also writes `evidence/ontology-kernel-acceptance.json` — digests plus the
ledger's reconcile output — so a reviewer can compare a later run against it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.bench import (
    authoring,
    distribution,
    extraction,
    ledger,
    ontology_import,
    templates,
    workspaces,
)
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

EVIDENCE_PATH = Path(__file__).resolve().parents[1] / "evidence" / "ontology-kernel-acceptance.json"


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    yield empty_db


def _schema() -> dict:
    return {
        "entity_types": ["company", "indicator"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": ["public", "internal", "confidential"],
        "corpus_declaration": {},
    }


def _domain(conn, key: str) -> dict:
    tmpl = templates.create_template(conn, name=f"tpl-{key}", schema=_schema(), created_by="admin-1")
    return workspaces.instantiate_domain(
        conn, key=key, name=f"Domain {key}", template_name=f"tpl-{key}",
        template_version=tmpl["version"], created_by="admin-1",
    )


def _seed(conn, key: str) -> None:
    for external_key, body in (("co-1", "公司一"), ("co-2", "公司二")):
        authoring.authoring_create_unit(
            conn, domain_key=key, kind="company", external_key=external_key,
            body=body, operator="expert-1",
        )
    authoring.authoring_create_unit(
        conn, domain_key=key, kind="indicator", external_key="ind-1",
        body="指标一", operator="expert-1",
    )
    authoring.authoring_create_relationship(
        conn, domain_key=key, kind="belongs_to", from_key="co-2", to_key="co-1",
        body="公司二 belongs_to 公司一", operator="expert-1",
    )


def test_publish_import_ledger_cycle(db_conn):
    key = "dom-accept"
    domain = _domain(db_conn, key)
    _seed(db_conn, key)

    first = distribution.publish_domain(db_conn, domain_key=key, published_by="lead-1")
    assert first["version"] == 1

    repeat = distribution.publish_domain(db_conn, domain_key=key, published_by="lead-1")
    assert (repeat["version"], repeat["digest"]) == (first["version"], first["digest"]), (
        "publishing unchanged content must not mint a second version"
    )

    payload = {
        "units": [
            {"kind": "company", "external_key": "co-3", "body": "公司三"},
            {"kind": "indicator", "external_key": "ind-2", "body": "指标二"},
        ],
        "relationships": [
            {"kind": "belongs_to", "from_key": "co-3", "to_key": "co-1"},
        ],
    }
    rows = ontology_import.plan(db_conn, domain_key=key, payload=payload)
    assert [row["action"] for row in rows] == ["create", "create", "create"]
    applied = ontology_import.apply(db_conn, domain_key=key, rows=rows, operator="expert-3")
    assert (applied["created"], applied["failed"]) == (3, 0), applied["failures"]

    again = ontology_import.plan(db_conn, domain_key=key, payload=payload)
    assert [row["action"] for row in again] == ["update", "update", "update"]
    reapplied = ontology_import.apply(db_conn, domain_key=key, rows=again, operator="expert-3")
    assert (reapplied["updated"], reapplied["failed"]) == (3, 0)

    second = distribution.publish_domain(db_conn, domain_key=key, published_by="lead-1")
    assert second["version"] == 2
    assert second["digest"] != first["digest"]

    # v1 must still be byte-identical after later content changed.
    v1 = distribution.get_publication(db_conn, domain_key=key, version=1)
    assert v1["digest"] == first["digest"]
    assert len(v1["manifest"]["entities"]) == 3
    assert distribution.get_publication(db_conn, domain_key=key)["version"] == 2

    snapshot = ledger.ledger(db_conn, domain=domain)
    assert snapshot["declaration"]["has_template"] is True
    assert snapshot["curation"]["total"] == 7   # seed 3 units + 1 rel, import 2 units + 1 rel
    assert snapshot["publication"]["latest"]["version"] == 2
    assert snapshot["reconcile"]["unused_kinds"] == []  # every declared kind now has content
    assert snapshot["reconcile"]["out_of_vocab_kinds"] == []
    assert snapshot["reconcile"]["consistent"] is True

    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(
            {
                "domain": key,
                "versions": [
                    {"version": first["version"], "digest": first["digest"]},
                    {"version": second["version"], "digest": second["digest"]},
                ],
                "import": {"created": applied["created"], "reimported": reapplied["updated"]},
                "ledger": {
                    "curation": snapshot["curation"],
                    "publication": snapshot["publication"],
                    "reconcile": snapshot["reconcile"],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_extraction_batch_files_proposals_and_counts_refusals(db_conn, monkeypatch):
    key = "dom-accept-extract"
    _domain(db_conn, key)
    chunk = {
        "chunk_id": "c1",
        "text": "第一条 合同应当采用书面形式。第二条 依法成立的合同受法律保护。",
        "title": "合同法",
        "library": "lib-1",
        "source_key": "src-1",
    }
    monkeypatch.setattr(
        extraction, "sample_chunks",
        lambda *args, **kwargs: {"chunks": [chunk], "cursor": None},
    )

    def complete(prompt: str) -> str:
        return json.dumps({
            "entities": [
                {"kind": "company", "name": "公司甲", "chunk_id": "c1",
                 "quote": "第一条 合同应当采用书面形式"},
                {"kind": "company", "name": "公司乙", "chunk_id": "c1",
                 "quote": "这句原文里根本没有"},
            ],
            "relationships": [],
        }, ensure_ascii=False)

    report = extraction.run(
        db_conn, domain_key=key, max_chunks=1, max_total=10, complete_fn=complete,
    )

    assert report["produced"] == 2
    assert report["submitted"] == 1
    assert report["skipped"]["bad_quote"] == 1
    assert report["usable_rate"] == 0.5
    assert report["low_yield"] is False           # exactly at the 0.5 threshold
    assert report["by_kind"] == {"company": 1}
    # A nomination must not change the ontology; it only lands in the inbox.
    assert authoring.authoring_list_units(db_conn, domain_key=key) == []
