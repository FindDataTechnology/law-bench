"""Hermetic tests for the per-pack flywheel export (task 6.4, P3).

Covers the domain-neutral kernel machine (``src.bench.flywheel``) and the
scripts-layer CLI (``scripts/finetune/export_by_pack.py``):

- labeled purposes route the whole material pool through the single-point
  guards in ``src.bench.tiers``: ``ground_truth`` rejects bronze (tiers' own
  assert) and rejects silver (gold-only fail-loud extension);
  ``reward_positive`` rejects silver; gold passes;
- warm-up (floor ``'silver'``) returns gold+silver and NEVER bronze/raw;
- exported JSONL rows carry tier + provenance that back-point to the source
  knowledge unit, and re-exports are byte-identical (idempotent);
- the scripts-layer guard re-export (``scripts/finetune/common.py`` ->
  ``src.bench.tiers``) keeps identical behavior (single source, no drift).

DB side uses the per-test ``empty_db`` fixture + ``ensure_schema(db_path=...)``
on the fixture's own connection (never the process-wide shared conn).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "finetune"))

from src.bench.flywheel import export_dataset  # noqa: E402
from src.bench.store import get_knowledge_unit, upsert_knowledge_unit  # noqa: E402
from src.bench.tiers import TIERS, TierGuardError  # noqa: E402
from src.eval.store import ensure_schema  # noqa: E402

KIND_MIXED = "flywheel-mixed"
KIND_GOLD = "flywheel-gold"
NS = "testns"
PACK = "test-pack"


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so DDL lands on the per-test DB
    # instead of the process-wide cached shared connection.
    ensure_schema(db_path=empty_db)
    yield empty_db


def _seed_four_tiers(conn) -> None:
    """One knowledge unit per tier under KIND_MIXED; gold-only KIND_GOLD."""
    for tier in ("raw", "bronze", "silver", "gold"):
        upsert_knowledge_unit(
            conn,
            kind=KIND_MIXED,
            namespace=NS,
            external_key=f"u-{tier}",
            body=f"body of {tier} unit",
            tags={"t": tier},
            attrs={"marker": f"MIXED-{tier.upper()}"},
            tier=tier,
            source_path=f"seed/{tier}",
            provenance={"origin": f"seed-{tier}"},
        )
    upsert_knowledge_unit(
        conn,
        kind=KIND_GOLD,
        namespace=NS,
        external_key="g-1",
        body="the only gold body",
        tier="gold",
        source_path="seed/gold",
        provenance={"origin": "seed-gold"},
    )


def _pool(*tiers: str) -> list[dict]:
    """In-memory material records (extract_fn adapter shape)."""
    return [
        {
            "external_key": f"k{i}",
            "namespace": NS,
            "body": f"pool body {i}",
            "tier": t,
            "provenance": {"origin": f"pool-{i}"},
        }
        for i, t in enumerate(tiers)
    ]


def _fn(records: list[dict]):
    def extract(kind: str) -> list[dict]:
        return list(records)

    return extract


def _rows(path: pathlib.Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# labeled purposes: the single-point guard rejects forbidden material loudly
# ---------------------------------------------------------------------------

def test_ground_truth_rejects_bronze_with_tiers_guard(db_conn, tmp_path):
    # bronze is rejected by src.bench.tiers.assert_not_ground_truth itself:
    # error text is tiers' message (carries tier + purpose).
    out = tmp_path / "gt.jsonl"
    with pytest.raises(TierGuardError) as ei:
        export_dataset(
            None, pack=PACK, kind="x", purpose="ground_truth",
            out_path=out, extract_fn=_fn(_pool("gold", "bronze")),
        )
    msg = str(ei.value)
    assert "tier='bronze'" in msg
    assert "purpose='ground_truth'" in msg
    # fail loud BEFORE writing: no partial dataset on disk.
    assert not out.exists()


def test_ground_truth_rejects_silver_gold_only(db_conn, tmp_path):
    # Silver is not a ground-truth-eligible tier for the flywheel: labeled
    # assembly is gold-only and trips the same guard type (fail loud).
    out = tmp_path / "gt.jsonl"
    with pytest.raises(TierGuardError) as ei:
        export_dataset(
            None, pack=PACK, kind="x", purpose="ground_truth",
            out_path=out, extract_fn=_fn(_pool("gold", "silver")),
        )
    msg = str(ei.value)
    assert "tier='silver'" in msg
    assert "purpose='ground_truth'" in msg


def test_ground_truth_rejects_full_four_tier_db_pool(db_conn, tmp_path):
    _seed_four_tiers(db_conn)
    out = tmp_path / "gt.jsonl"
    with pytest.raises(TierGuardError) as ei:
        export_dataset(
            db_conn, pack=PACK, kind=KIND_MIXED, purpose="ground_truth",
            out_path=out,
        )
    msg = str(ei.value)
    assert "tier=" in msg and "purpose='ground_truth'" in msg
    assert not out.exists()


def test_reward_positive_rejects_silver(db_conn, tmp_path):
    # reward_positive: tiers._REWARD_POSITIVE_FLOORS forbids bronze AND silver;
    # the silver record trips the assert with tiers' own message.
    out = tmp_path / "rp.jsonl"
    with pytest.raises(TierGuardError) as ei:
        export_dataset(
            None, pack=PACK, kind="x", purpose="reward_positive",
            out_path=out, extract_fn=_fn(_pool("gold", "silver")),
        )
    msg = str(ei.value)
    assert "tier='silver'" in msg
    assert "purpose='reward_positive'" in msg


def test_gold_only_ground_truth_passes(db_conn, tmp_path):
    _seed_four_tiers(db_conn)
    out = tmp_path / "gt.jsonl"
    stats = export_dataset(
        db_conn, pack=PACK, kind=KIND_GOLD, purpose="ground_truth", out_path=out
    )
    assert stats["exported"] == 1
    assert stats["tiers"]["gold"] == 1
    rows = _rows(out)
    assert [r["tier"] for r in rows] == ["gold"]


def test_labeled_rejects_sub_gold_floor_request(db_conn, tmp_path):
    # A labeled request asking for a silver floor is a policy error.
    _seed_four_tiers(db_conn)
    with pytest.raises(ValueError):
        export_dataset(
            db_conn, pack=PACK, kind=KIND_GOLD, purpose="ground_truth",
            tier_floor="silver", out_path=tmp_path / "x.jsonl",
        )


# ---------------------------------------------------------------------------
# warm-up: floor filtering only — gold+silver, never bronze/raw
# ---------------------------------------------------------------------------

def test_warmup_floor_silver_returns_only_gold_and_silver(db_conn, tmp_path):
    _seed_four_tiers(db_conn)
    out = tmp_path / "warm.jsonl"
    stats = export_dataset(
        db_conn, pack=PACK, kind=KIND_MIXED, purpose="sft_warmup",
        tier_floor="silver", out_path=out,
    )
    assert stats["exported"] == 2
    rows = _rows(out)
    assert {r["tier"] for r in rows} == {"gold", "silver"}
    assert {r["external_key"] for r in rows} == {"u-gold", "u-silver"}
    text = out.read_text(encoding="utf-8")
    assert "u-bronze" not in text
    assert "u-raw" not in text
    assert '"bronze"' not in text
    assert '"raw",' not in text  # no row carries a raw/bronze tier tag


def test_warmup_default_floor_is_silver(db_conn, tmp_path):
    _seed_four_tiers(db_conn)
    out = tmp_path / "warm.jsonl"
    stats = export_dataset(
        db_conn, pack=PACK, kind=KIND_MIXED, purpose="sft_warmup", out_path=out
    )
    assert stats["tier_floor"] == "silver"
    assert stats["exported"] == 2
    rows = _rows(out)
    assert all(r["tier"] in ("gold", "silver") for r in rows)


# ---------------------------------------------------------------------------
# row shape: provenance back-pointer + tier on every record; idempotent bytes
# ---------------------------------------------------------------------------

def test_rows_carry_tier_and_back_pointing_provenance(db_conn, tmp_path):
    _seed_four_tiers(db_conn)
    out = tmp_path / "gt.jsonl"
    export_dataset(
        db_conn, pack=PACK, kind=KIND_GOLD, purpose="ground_truth", out_path=out
    )
    rows = _rows(out)
    assert rows
    for row in rows:
        assert row["tier"] in TIERS
        prov = row["provenance"]
        assert prov["pack"] == PACK
        assert prov["source_ref"] == f"{NS}/{KIND_GOLD}/{row['external_key']}"
        # back-reference resolves to the stored source unit
        unit = get_knowledge_unit(
            db_conn, kind=row["kind"], external_key=row["external_key"],
            namespace=row["namespace"],
        )
        assert unit is not None
        assert prov["unit_id"] == unit["id"]
        assert row["body"] == unit["body"]
        # original unit provenance is preserved alongside the export stamp
        assert prov["origin"] == "seed-gold"


def test_export_is_idempotent(db_conn, tmp_path):
    _seed_four_tiers(db_conn)
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    export_dataset(
        db_conn, pack=PACK, kind=KIND_MIXED, purpose="sft_warmup", out_path=a
    )
    export_dataset(
        db_conn, pack=PACK, kind=KIND_MIXED, purpose="sft_warmup", out_path=b
    )
    assert a.read_bytes() == b.read_bytes()
    # labeled too
    export_dataset(
        db_conn, pack=PACK, kind=KIND_GOLD, purpose="ground_truth", out_path=a
    )
    export_dataset(
        db_conn, pack=PACK, kind=KIND_GOLD, purpose="ground_truth", out_path=b
    )
    assert a.read_bytes() == b.read_bytes()


# ---------------------------------------------------------------------------
# domain adaptation: injected extract_fn (no DB needed at all)
# ---------------------------------------------------------------------------

def test_extract_fn_override_kind_and_conn_none(tmp_path):
    seen: list[str] = []

    def extract(kind: str) -> list[dict]:
        seen.append(kind)
        return _pool("gold")

    out = tmp_path / "adapted.jsonl"
    stats = export_dataset(
        None, pack="some-pack", kind="indicator", purpose="ground_truth",
        out_path=out, extract_fn=extract,
    )
    assert seen == ["indicator"]
    assert stats["exported"] == 1
    rows = _rows(out)
    assert rows[0]["kind"] == "indicator"
    assert rows[0]["tier"] == "gold"


def test_invalid_tier_record_fails_closed(tmp_path):
    rec = {"external_key": "z", "tier": "platinum", "body": "x"}
    with pytest.raises(ValueError):
        export_dataset(
            None, pack=PACK, kind="x", purpose="sft_warmup",
            out_path=tmp_path / "y.jsonl", extract_fn=_fn([rec]),
        )


# ---------------------------------------------------------------------------
# scripts-layer re-export (common.py) keeps guard semantics after the move
# ---------------------------------------------------------------------------

def test_common_reexport_guard_semantics_unchanged():
    import common  # scripts/finetune/common.py (re-export shim)
    from src.bench import tiers

    # single source: the re-exports are the very same objects
    assert common.assert_not_ground_truth is tiers.assert_not_ground_truth
    assert common.filter_by_tier is tiers.filter_by_tier
    assert common.TierGuardError is TierGuardError
    assert common.TIERS is tiers.TIERS

    # bronze still refused through the scripts-layer import path
    with pytest.raises(common.TierGuardError) as ei:
        common.assert_not_ground_truth("bronze")
    assert "tier='bronze'" in str(ei.value)
    with pytest.raises(common.TierGuardError):
        common.assert_not_ground_truth("bronze", purpose="reward_positive")
    # gold passes silently
    common.assert_not_ground_truth("gold", purpose="ground_truth")
    # filter semantics unchanged
    kept = common.filter_by_tier(_pool("gold", "silver", "bronze", "raw"), "silver")
    assert [r["tier"] for r in kept] == ["gold", "silver"]


# ---------------------------------------------------------------------------
# scripts/finetune/export_by_pack.py: legal adapter + CLI contract
# ---------------------------------------------------------------------------

def test_legal_clause_adapter_maps_legacy_tables(db_conn, tmp_path):
    import export_by_pack as ebp

    assert "legal:clause" in ebp.ADAPTERS

    # live clauses schema: category/level were dropped by the additive-columns
    # migration; required columns are contract_type/section/body/body_hash.
    db_conn.execute(
        "INSERT INTO clauses (contract_type, section, body, body_hash,"
        " created_at, updated_at) VALUES"
        " (%s, 'sec-1', 'legacy material body', 'h1', 't', 't')",
        ("sale",),
    )
    records = list(ebp.legal_clause_material(db_conn, "legal", "clause"))
    assert records, "clauses row should map to material"
    raw = [r for r in records if r["tier"] == "raw"]
    assert raw and raw[0]["body"] == "legacy material body"
    assert raw[0]["provenance"]["table"] == "clauses"
    assert all(r["tier"] in TIERS for r in records)

    # the same single-point guards apply to real vertical material:
    out = tmp_path / "gt.jsonl"
    with pytest.raises(TierGuardError):
        export_dataset(
            None, pack="legal", kind="clause", purpose="ground_truth",
            out_path=out, extract_fn=lambda k: records,
        )
    # warm-up with an explicit raw floor exports the structural corpus
    warm = tmp_path / "warm.jsonl"
    stats = export_dataset(
        None, pack="legal", kind="clause", purpose="sft_warmup",
        tier_floor="raw", out_path=warm, extract_fn=lambda k: records,
    )
    assert stats["exported"] == len([r for r in records if r["tier"] == "raw"])


def test_cli_help_exits_zero():
    script = REPO_ROOT / "scripts" / "finetune" / "export_by_pack.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--pack" in proc.stdout and "--kind" in proc.stdout


def test_cli_end_to_end_guard_and_warmup(db_conn, tmp_path):
    # empty_db already monkeypatched database_url to this test's DB.
    import export_by_pack as ebp

    db_conn.execute(
        "INSERT INTO clauses (contract_type, section, body, body_hash,"
        " created_at, updated_at) VALUES"
        " (%s, 'sec-2', 'cli legacy body', 'h2', 't', 't')",
        ("lease",),
    )
    db_conn.commit()

    gt = tmp_path / "gt.jsonl"
    rc = ebp.main([
        "--pack", "legal", "--kind", "clause", "--purpose", "ground_truth",
        "--out", str(gt),
    ])
    assert rc == 3  # guard trip: raw/bronze pool cannot be a labeled set
    assert not gt.exists()

    warm = tmp_path / "warm.jsonl"
    rc = ebp.main([
        "--pack", "legal", "--kind", "clause", "--purpose", "sft_warmup",
        "--tier-floor", "raw", "--out", str(warm),
    ])
    assert rc == 0
    rows = _rows(warm)
    assert rows and all(r["tier"] == "raw" for r in rows)
    assert all(r["provenance"]["pack"] == "legal" for r in rows)

    # kind not declared by the pack's manifest -> request-level refusal
    rc = ebp.main([
        "--pack", "legal", "--kind", "not-a-kind", "--purpose", "sft_warmup",
        "--out", str(tmp_path / "z.jsonl"),
    ])
    assert rc == 2
