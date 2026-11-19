"""Crosswalk coverage and gap reporting (change add-crosswalk-seam, tasks 5.1-5.3).

The two rules worth pinning:

- **coverage counts entities, not mapping rows.** Ten mappings on one entity
  must contribute exactly as much as one — otherwise the ratio can be inflated
  by hanging more rows on the same thing, which is what a quality metric exists
  to prevent.
- **the two crosswalk gaps stay separate.** "The external system changed" and
  "nobody has looked at this yet" need different people to do different things;
  a merged count tells an operator "mappings are broken" and nothing else.
"""

from __future__ import annotations

import pytest

from src.bench import quality, store
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    yield empty_db


NS = "erp"


def _entity(db_conn, key: str) -> None:
    store.upsert_knowledge_unit(
        db_conn, kind="organization", namespace=NS, external_key=key, body="x"
    )


def _crosswalk(db_conn, key: str, *, confidence=0.95, connectivity=None) -> None:
    attrs = {
        "relation": "same_as",
        "peer": {"kind": "external_id", "system": "salesforce", "id": "x"},
    }
    if confidence is not None:
        attrs["confidence"] = confidence
    if connectivity is not None:
        attrs["connectivity"] = connectivity
    store.upsert_knowledge_unit(
        db_conn, kind="crosswalk", namespace=NS, external_key=key, body="m", attrs=attrs
    )


def _complete(ok=True):
    return {
        s: {"ok": ok, "evidence": f"proof-{s}"}
        for s in ("catalog", "executor_tests", "live")
    }


# ----------------------------------------------------------------- coverage


def test_coverage_counts_entities_not_rows(db_conn):
    """Ten mappings on one entity == one mapping, for coverage purposes."""
    for key in ("organization:a", "organization:b"):
        _entity(db_conn, key)
    # Five confirmed mappings, all about entity a.
    for _ in range(5):
        _crosswalk(db_conn, "organization:a", confidence=0.95)
    metric = quality.crosswalk_coverage(db_conn, namespace=NS)
    assert metric["denominator"] == 2, "denominator is live entities"
    assert metric["numerator"] == 1, "one entity covered, regardless of row count"


def test_unconfirmed_mappings_do_not_count(db_conn):
    _entity(db_conn, "organization:a")
    _crosswalk(db_conn, "organization:a", confidence=None)  # unreviewed
    metric = quality.crosswalk_coverage(db_conn, namespace=NS)
    assert metric["numerator"] == 0
    assert metric["value"] == 0.0


def test_low_confidence_does_not_count(db_conn):
    _entity(db_conn, "organization:a")
    _crosswalk(db_conn, "organization:a", confidence=0.2)
    assert quality.crosswalk_coverage(db_conn, namespace=NS)["numerator"] == 0


def test_no_entities_reports_none_not_zero(db_conn):
    """An empty domain has nothing to cover — that is not "0% coverage"."""
    assert quality.crosswalk_coverage(db_conn, namespace=NS)["value"] is None


# --------------------------------------------------------------------- gaps


def test_stale_and_unconfirmed_are_counted_separately(db_conn):
    _entity(db_conn, "organization:a")
    _entity(db_conn, "organization:b")
    # a: claims connectivity but live is missing → stale
    _crosswalk(
        db_conn, "organization:a", confidence=0.95,
        connectivity={"catalog": {"ok": True, "evidence": "c"},
                      "executor_tests": {"ok": True, "evidence": "e"}},
    )
    # b: no confidence at all → unconfirmed
    _crosswalk(db_conn, "organization:b", confidence=None)

    gaps = quality.crosswalk_gaps(db_conn, namespace=NS)
    assert [row["key"] for row in gaps["stale"]] == ["organization:a"]
    assert gaps["stale"][0]["missing"] == ["live"]
    assert gaps["unconfirmed"] == ["organization:b"]


def test_complete_connectivity_is_not_stale(db_conn):
    _entity(db_conn, "organization:a")
    _crosswalk(db_conn, "organization:a", connectivity=_complete())
    assert quality.crosswalk_gaps(db_conn, namespace=NS)["stale"] == []


def test_a_crosswalk_without_connectivity_is_not_stale(db_conn):
    """No connectivity block = unverified, not overdue. Different remedies."""
    _entity(db_conn, "organization:a")
    _crosswalk(db_conn, "organization:a", confidence=0.9)
    assert quality.crosswalk_gaps(db_conn, namespace=NS)["stale"] == []


# ------------------------------------------------------------- dispatch routes


def test_each_crosswalk_gap_has_its_own_route(db_conn):
    from src.bench import dispatch

    for gap in ("quality:crosswalk", "quality:crosswalk_stale",
                "quality:crosswalk_unconfirmed"):
        assert dispatch.route_for(gap) == dispatch.FLEET_ROUTE
        assert gap in dispatch.GAP_TASKS, "every routable gap needs a task title"


def test_crosswalk_metric_appears_in_all_metrics(db_conn):
    _entity(db_conn, "organization:a")
    _crosswalk(db_conn, "organization:a")
    metrics = quality.all_metrics(db_conn, domain_key=NS, namespace=NS)
    assert "crosswalk" in metrics
    assert metrics["crosswalk"]["denominator"] == 1


def test_crosswalk_is_not_counted_as_a_relationship(db_conn):
    """A crosswalk is an assertion about an entity, never an edge in the graph.

    Its key normally has no "->", so the relationship query skips it by luck.
    This pins the explicit exclusion: a key that *did* contain an arrow must
    still not pollute referential integrity.
    """
    _entity(db_conn, "organization:a")
    _crosswalk(db_conn, "a->b:crosswalk-looking-key")
    metric = quality.referential_integrity(db_conn, namespace=NS)
    assert metric["denominator"] == 0, "crosswalks are not relationships"
