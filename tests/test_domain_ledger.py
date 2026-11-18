"""Domain ontology ledger (src/bench/ledger.py).

Runs against ``empty_db`` + ``ensure_schema`` (the full kernel schema), the
same fixture style as ``tests/test_domain_proposals.py``. Covers the ledger's
contract as a pure read projection: honest empty states (including a dangling
template anchor), the declaration-vs-curation reconciliation diff, verbatim
publication digests (never recomputed), domain-scoped consumer pull
footprints, and the hard rule that no credential material is ever returned.
"""

from __future__ import annotations

import json

import pytest
from psycopg.rows import dict_row, tuple_row

from src.bench import authoring, distribution, ledger, store, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so DDL lands on the per-test DB
    # instead of the process-wide cached shared connection.
    ensure_schema(db_path=empty_db)
    yield empty_db


def authoring_schema(
    *,
    entity_types: list[str] | None = None,
    relationship_kinds: list[str] | None = None,
) -> dict:
    """Template schema aligned with the kernel vocabularies."""
    return {
        "entity_types": list(entity_types or ["company", "indicator", "contract"]),
        "concept_structures": {},
        "relationship_kinds": list(relationship_kinds or ["belongs_to"]),
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }


def make_domain(conn, key: str, *, schema: dict | None = None) -> dict:
    """One template + one domain instantiated from it; return the domain."""
    tmpl = templates.create_template(
        conn,
        name=f"tpl-{key}",
        schema=schema or authoring_schema(),
        created_by="admin-1",
    )
    return workspaces.instantiate_domain(
        conn,
        key=key,
        name=f"Domain {key}",
        template_name=f"tpl-{key}",
        template_version=tmpl["version"],
        created_by="admin-1",
    )


def make_unit(conn, *, domain_key: str, kind: str, external_key: str) -> dict:
    """Author one entity unit through the kernel write path."""
    return authoring.authoring_create_unit(
        conn,
        domain_key=domain_key,
        kind=kind,
        external_key=external_key,
        body=f"{kind} {external_key}",
        operator="expert-1",
    )


# ------------------------------------------------------------- 诚实空态


def test_empty_domain_reports_honest_emptiness_and_ledger_does_not_raise(db_conn):
    """A brand-new domain: template anchor present, everything else genuinely
    empty — zero counts, zero rows, no fabricated distribution."""
    domain = make_domain(db_conn, "dom-empty")

    snap = ledger.ledger(db_conn, domain=domain)

    dec = snap["declaration"]
    assert dec["has_template"] is True
    assert dec["template"] == {
        "id": domain["template_id"],
        "name": "tpl-dom-empty",
        "version": 1,
        "latest_version": 1,
        "is_latest": True,
    }
    assert dec["entity_types"] == ["company", "indicator", "contract"]
    assert dec["relationship_kinds"] == ["belongs_to"]
    assert dec["tier_vocabulary"] == list(TIERS)
    assert dec["sensitivity_vocabulary"] == list(SENSITIVITY_LEVELS)
    assert dec["template_version"] == 1
    assert dec["source"] == "ontology_templates"

    cur = snap["curation"]
    assert cur["total"] == 0
    assert cur["by_kind"] == []
    assert cur["by_tier"] == {"raw": 0, "bronze": 0, "silver": 0, "gold": 0}
    assert cur["recent_events"] == []
    assert cur["deleted"] == 0
    assert cur["source"] == "knowledge_units"

    pub = snap["publication"]
    assert pub["has_publication"] is False
    assert pub["latest"] is None
    assert pub["history"] == []
    assert pub["source"] == "ontology_publications"

    con = snap["consumption"]
    assert con["consumers"] == []
    assert con["source"] == "distribution_consumers + distribution_pull_events"

    rec = snap["reconcile"]
    assert rec["out_of_vocab_kinds"] == []
    assert rec["unused_kinds"] == ["company", "indicator", "contract", "belongs_to"]
    assert rec["template_outdated"] is False
    assert rec["consistent"] is False
    assert rec["summary_key"] == "ledger.reconcile.gaps"


def test_missing_template_anchor_is_reported_not_raised(db_conn):
    """A dangling anchor is a page state ("no template anchor"), not an error:
    the declaration layer goes empty and the other layers still read."""
    domain = make_domain(db_conn, "dom-noanchor")
    dangling = dict(domain, template_id=10**9)

    dec = ledger.declaration_layer(db_conn, domain=dangling)
    assert dec["has_template"] is False
    assert dec["entity_types"] == []
    assert dec["relationship_kinds"] == []
    assert dec["tier_vocabulary"] == []
    assert dec["sensitivity_vocabulary"] == []
    assert dec["template"]["name"] is None
    assert dec["template"]["version"] is None
    assert dec["template"]["latest_version"] is None
    assert dec["template"]["is_latest"] is False

    snap = ledger.ledger(db_conn, domain=dangling)
    assert snap["curation"]["total"] == 0
    assert snap["publication"]["has_publication"] is False
    assert snap["consumption"]["consumers"] == []


# ------------------------------------------- 声明与策展的一致性核对


def test_two_of_three_entity_kinds_used_reports_the_third_unused(db_conn):
    """company+indicator used, contract declared but unused -> exactly
    ``contract`` is the coverage gap; lanes label the two vocabularies."""
    domain = make_domain(db_conn, "dom-gap")
    make_unit(db_conn, domain_key="dom-gap", kind="company", external_key="c-1")
    make_unit(db_conn, domain_key="dom-gap", kind="indicator", external_key="i-1")
    authoring.authoring_create_relationship(
        db_conn,
        domain_key="dom-gap",
        kind="belongs_to",
        from_key="c-1",
        to_key="i-1",
        body="company belongs to indicator",
        operator="expert-1",
    )

    lanes = {
        row["kind"]: row["lane"]
        for row in ledger.curation_layer(db_conn, domain=domain)["by_kind"]
    }
    assert lanes == {
        "company": "entity",
        "indicator": "entity",
        "belongs_to": "relationship",
    }

    rec = ledger.reconcile(db_conn, domain=domain)
    assert rec["unused_kinds"] == ["contract"]
    assert rec["out_of_vocab_kinds"] == []
    assert rec["template_outdated"] is False
    assert rec["consistent"] is False
    assert rec["summary_key"] == "ledger.reconcile.gaps"


def test_out_of_vocabulary_unit_is_flagged(db_conn):
    """A stored kind in neither vocabulary is an anomaly the diff names."""
    domain = make_domain(db_conn, "dom-oov")
    store.upsert_knowledge_unit(
        db_conn,
        kind="gadget",
        external_key="g-1",
        body="not in either vocabulary",
        namespace="dom-oov",
    )

    rec = ledger.reconcile(db_conn, domain=domain)
    assert "gadget" in rec["out_of_vocab_kinds"]
    assert rec["consistent"] is False
    assert rec["summary_key"] == "ledger.reconcile.gaps"


# ------------------------------------------------------- 发布层 digest 单源


def test_publication_digest_is_returned_verbatim(db_conn):
    """The ledger reports the stored digest byte-for-byte — never a recompute."""
    domain = make_domain(db_conn, "dom-pub")
    make_unit(db_conn, domain_key="dom-pub", kind="company", external_key="c-1")
    published = distribution.publish_domain(
        db_conn, domain_key="dom-pub", published_by="lead-1"
    )
    stored = db_conn.execute(
        "SELECT digest FROM ontology_publications WHERE domain_id = %s AND version = 1",
        (domain["id"],),
    ).fetchone()["digest"]

    layer = ledger.publication_layer(db_conn, domain=domain)
    assert layer["has_publication"] is True
    assert layer["latest"]["version"] == 1
    assert layer["latest"]["digest"] == stored == published["digest"]
    assert layer["latest"]["published_by"] == "lead-1"
    assert isinstance(layer["latest"]["changelog"], dict)
    assert layer["history"] == [layer["latest"]]


# ------------------------------------------------------------ 消费层足迹


def test_consumer_pull_footprint_is_domain_scoped(db_conn):
    """Only consumers bound to THIS domain appear; last_pull is the newest
    event row, and a different domain's consumer never leaks in."""
    domain_a = make_domain(db_conn, "dom-cons-a")
    domain_b = make_domain(db_conn, "dom-cons-b")
    distribution.register_consumer(
        db_conn,
        name="feed-a",
        domains=["dom-cons-a"],
        token_hash="hash-a",
        created_by="admin-1",
    )
    distribution.register_consumer(
        db_conn,
        name="feed-b",
        domains=["dom-cons-b"],
        token_hash="hash-b",
        created_by="admin-1",
    )

    layer = ledger.consumption_layer(db_conn, domain=domain_a)
    assert [c["name"] for c in layer["consumers"]] == ["feed-a"]
    assert layer["consumers"][0]["domains"] == ["dom-cons-a"]
    assert layer["consumers"][0]["revoked"] is False
    assert layer["consumers"][0]["last_pull"] is None

    consumer_id = db_conn.execute(
        "SELECT id FROM distribution_consumers WHERE name = 'feed-a'"
    ).fetchone()["id"]
    db_conn.execute(
        "INSERT INTO distribution_pull_events "
        "(consumer_id, domain_key, version, happened_at) VALUES "
        "(%s, %s, %s, now() - interval '1 day'), (%s, %s, %s, now())",
        (consumer_id, "dom-cons-a", 1, consumer_id, "dom-cons-a", 3),
    )
    db_conn.commit()

    after_pull = ledger.consumption_layer(db_conn, domain=domain_a)["consumers"][0]
    assert after_pull["last_pull"]["version"] == 3
    assert after_pull["last_pull"]["happened_at"] is not None

    # B's ledger sees only its own consumer, and A did not bleed through.
    b_consumers = ledger.consumption_layer(db_conn, domain=domain_b)["consumers"]
    assert [c["name"] for c in b_consumers] == ["feed-b"]

    # Revocation is a status flag, not a removal from the layer.
    distribution.revoke_consumer(db_conn, name="feed-a")
    revoked = ledger.consumption_layer(db_conn, domain=domain_a)["consumers"][0]
    assert revoked["revoked"] is True
    assert revoked["last_pull"]["version"] == 3


def test_no_credential_material_appears_in_the_ledger(db_conn):
    """``token_hash`` is never selected, so neither the key nor its value can
    reach the page payload (the spec forbids exposing credential material)."""
    domain = make_domain(db_conn, "dom-secret")
    make_unit(db_conn, domain_key="dom-secret", kind="company", external_key="c-1")
    secret = "sha256:deadbeefdeadbeefdeadbeefdeadbeef"
    distribution.register_consumer(
        db_conn,
        name="feed-secret",
        domains=["dom-secret"],
        token_hash=secret,
        created_by="admin-1",
    )

    payload = json.dumps(ledger.ledger(db_conn, domain=domain))
    assert "token_hash" not in payload
    assert secret not in payload


# ------------------------------------------------------- 行形状容忍（元组）


def test_tuple_row_connections_are_supported(db_conn):
    """The projection decodes plain tuple cursors exactly like dict rows."""
    domain = make_domain(db_conn, "dom-rows")
    make_unit(db_conn, domain_key="dom-rows", kind="company", external_key="c-1")
    distribution.publish_domain(db_conn, domain_key="dom-rows", published_by="lead-1")

    db_conn.row_factory = tuple_row
    try:
        snap = ledger.ledger(db_conn, domain=domain)
    finally:
        db_conn.row_factory = dict_row

    assert snap["declaration"]["template"]["name"] == "tpl-dom-rows"
    assert snap["curation"]["total"] == 1
    assert snap["curation"]["by_kind"] == [
        {"kind": "company", "count": 1, "lane": "entity"}
    ]
    assert snap["publication"]["latest"]["version"] == 1
    assert snap["consumption"]["consumers"] == []
