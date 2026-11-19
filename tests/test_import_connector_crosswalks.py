"""Connector evidence → crosswalk units (change add-crosswalk-seam, task 3.3).

The import is deliberately literal: `connectivity` is copied verbatim from the
ERP file, and **no confidence is invented**. That is the whole point of the
three-state discipline — the file says how far each integration has been
verified, not how sure anyone is that the mapping is right. Synthesising a
confidence would count as reviewed something nobody reviewed, and the coverage
ratio would then be inflated by exactly the rows still awaiting review.

Two units per integration, because a crosswalk must point at a real endpoint and
the proposal inbox refuses to manufacture one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import import_connector_crosswalks as importer  # noqa: E402


def status(*integrations) -> dict:
    return {"integrations": list(integrations)}


def integration(provider: str, template: str, **states) -> dict:
    base = {
        "provider": provider,
        "template": template,
        "external_system": provider.title(),
        "state": "not_connected",
        "states": {
            "catalog": {"ok": states.get("catalog", False), "evidence": "c.json"},
            "executor_tests": {"ok": states.get("executor_tests", False), "evidence": "t.ts"},
            "live": {"ok": states.get("live", False), "evidence": None},
        },
    }
    return base


# ------------------------------------------------------------------- plans


def test_one_crosswalk_per_template_and_provider():
    """The same provider twice (two verticals) is two distinct bindings."""
    rows = importer.plans(
        status(integration("wechatpay", "restaurant-chain"),
               integration("wechatpay", "supply-chain")),
        target="organization",
    )
    assert len(rows) == 2, "keying by provider alone would collapse them"


def test_duplicate_provider_within_one_template_is_deduped():
    rows = importer.plans(
        status(integration("kingdee", "supply-chain"),
               integration("kingdee", "supply-chain")),
        target="organization",
    )
    assert len(rows) == 1


def test_connectivity_is_copied_verbatim():
    rows = importer.plans(
        status(integration("shopify_admin", "crossborder", catalog=True,
                           executor_tests=True, live=False)),
        target="organization",
    )
    conn = rows[0]["connectivity"]
    assert conn["catalog"]["ok"] is True
    assert conn["live"]["ok"] is False
    assert rows[0]["missing"] == ["live"]


def test_no_confidence_is_invented():
    """The ERP file says nothing about how sure anyone is — so we say nothing."""
    rows = importer.plans(
        status(integration("kingdee", "supply-chain", catalog=True)), target="organization"
    )
    assert "confidence" not in rows[0], (
        "a synthesised confidence would count as reviewed something nobody reviewed"
    )


def test_missing_states_are_listed_in_clearance_order():
    rows = importer.plans(
        status(integration("pos", "restaurant-chain", catalog=True)), target="organization"
    )
    assert rows[0]["missing"] == ["executor_tests", "live"]


def test_fully_connected_reports_no_missing():
    rows = importer.plans(
        status(integration("wms", "supply-chain", catalog=True,
                           executor_tests=True, live=True)),
        target="organization",
    )
    assert rows[0]["missing"] == []


def test_rows_without_provider_or_template_are_skipped():
    rows = importer.plans(
        status({"provider": "", "template": "x"}, {"provider": "y", "template": ""}),
        target="organization",
    )
    assert rows == []


# ---------------------------------------------------------------- real file


def test_plans_validate_against_the_real_crosswalk_rules():
    """Whatever we import must pass the same predicate the proposal inbox uses."""
    from src.bench import crosswalk as cw

    real = REPO_ROOT.parent / "fd-erp-vertical-templates" / "connector-status.json"
    if not real.is_file():
        pytest.skip("ERP checkout not present")
    rows = importer.plans(json.loads(real.read_text(encoding="utf-8")),
                          target="organization")
    assert rows, "the real file has integrations"
    for row in rows:
        attrs = {
            "relation": "same_as",
            "peer": {"kind": "external_id", "system": row["provider"],
                     "id": row["provider"]},
            "connectivity": row["connectivity"],
        }
        assert cw.validate_crosswalk(attrs) == [], row["provider"]
