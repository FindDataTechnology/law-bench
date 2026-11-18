"""Domain bench catalog (src/bench/domain_assets.py).

Runs against ``empty_db`` + ``ensure_schema`` (the full kernel schema), the
same fixture style as ``tests/test_domain_proposals.py`` / ``tests/test_domain_ledger.py``.
The harbor rubric/prompt tables come from ``src.eval.harbor_seed.create_schema``
and are created in the fixture because ``ensure_schema`` does not own them.

Covers the directory contract: assignment is idempotent and many-to-many,
unassigning never touches the asset, unknown kinds/blank keys are refused,
deleted assets surface as orphans and can be purged, the unassigned pool
excludes anything catalogued by *any* domain, and the module stays out of the
evaluation path.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from src.bench import domain_assets, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.harbor_seed import create_schema as create_harbor_schema
from src.eval.store import ensure_schema

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so DDL lands on the per-test DB
    # instead of the process-wide cached shared connection.
    ensure_schema(db_path=empty_db)
    # rubrics / prompts are harbor_seed's tables, not ensure_schema's; the
    # catalog needs the real DDL to exist before it can project them.
    create_harbor_schema(empty_db)
    yield empty_db


def authoring_schema() -> dict:
    """Template schema aligned with the kernel vocabularies."""
    return {
        "entity_types": ["company", "indicator"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }


def make_domain(conn, key: str) -> dict:
    """One template + one domain instantiated from it; return the domain."""
    tmpl = templates.create_template(
        conn, name=f"tpl-{key}", schema=authoring_schema(), created_by="admin-1"
    )
    return workspaces.instantiate_domain(
        conn,
        key=key,
        name=f"Domain {key}",
        template_name=f"tpl-{key}",
        template_version=tmpl["version"],
        created_by="admin-1",
    )


def make_rubric(conn, name: str) -> None:
    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, "
        "created_at) VALUES (%s, 'check', 'local', NULL, '', " "'2026-01-01T00:00:00+00:00')",
        (name,),
    )
    conn.commit()


def make_prompt(conn, name: str) -> None:
    conn.execute(
        "INSERT INTO prompts (name, contract_type, purpose, content, source, "
        "created_at) VALUES (%s, 'software', 'judge', 'body', 'local', "
        "'2026-01-01T00:00:00+00:00')",
        (name,),
    )
    conn.commit()


def make_compare(conn, label: str | None) -> int:
    row = conn.execute(
        "INSERT INTO compare_runs (label, created_at) "
        "VALUES (%s, '2026-01-01T00:00:00+00:00') RETURNING id",
        (label,),
    ).fetchone()
    conn.commit()
    return row["id"]


def make_sample(conn, body_hash: str, *, scenario: str | None = None) -> None:
    conn.execute(
        "INSERT INTO contract_artifacts "
        "(contract_type, scenario, stance, body_hash, body_text, minio_bucket, "
        "created_at, updated_at) "
        "VALUES ('software', %s, 'neutral', %s, 'text', 'bucket', "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
        (scenario, body_hash),
    )
    conn.commit()


def make_clause(conn, section: str) -> int:
    row = conn.execute(
        "INSERT INTO clauses (contract_type, section, body, body_hash, "
        "created_at, updated_at) "
        "VALUES ('software', %s, 'body', %s, '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00') RETURNING id",
        (section, f"hash-{section}"),
    ).fetchone()
    conn.commit()
    return row["id"]


def make_law_info(conn, contract_type: str, *, source: str = "national") -> None:
    conn.execute(
        "INSERT INTO law_info (contract_type, source, content, created_at) "
        "VALUES (%s, %s, 'content', '2026-01-01T00:00:00+00:00')",
        (contract_type, source),
    )
    conn.commit()


def count_rows(conn, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def item_keys(group: dict) -> list[str]:
    return [item["asset_key"] for item in group["items"]]


def group_of(listing: dict, kind: str) -> dict | None:
    for group in listing["groups"]:
        if group["kind"] == kind:
            return group
    return None


# ------------------------------------------------------------- 幂等与多对多


def test_assign_twice_leaves_one_row_and_returns_the_original_record(db_conn):
    make_domain(db_conn, "dom-a")
    make_rubric(db_conn, "r1")

    first = domain_assets.assign(
        db_conn, domain_key="dom-a", asset_kind="rubric",
        asset_key="r1", added_by="lead-1",
    )
    second = domain_assets.assign(
        db_conn, domain_key="dom-a", asset_kind="rubric",
        asset_key="r1", added_by="lead-2",
    )

    assert first["asset_key"] == "r1"
    # Idempotent: the second call is a no-op, so the first cataloguer stays on
    # record and the row is byte-identical.
    assert second == first
    assert first["added_by"] == "lead-1"
    assert count_rows(db_conn, "SELECT COUNT(*) AS n FROM domain_assets") == 1


def test_same_asset_in_two_domains_and_unassign_leaves_asset_untouched(db_conn):
    make_domain(db_conn, "dom-a")
    make_domain(db_conn, "dom-b")
    make_rubric(db_conn, "r1")
    before = db_conn.execute(
        "SELECT * FROM rubrics WHERE name = 'r1'"
    ).fetchone()

    for domain_key in ("dom-a", "dom-b"):
        domain_assets.assign(
            db_conn, domain_key=domain_key, asset_kind="rubric",
            asset_key="r1", added_by="lead-1",
        )

    listing_a = domain_assets.list_for_domain(db_conn, domain_key="dom-a")
    listing_b = domain_assets.list_for_domain(db_conn, domain_key="dom-b")
    assert item_keys(group_of(listing_a, "rubric")) == ["r1"]
    assert item_keys(group_of(listing_b, "rubric")) == ["r1"]

    assert domain_assets.unassign(
        db_conn, domain_key="dom-a", asset_kind="rubric", asset_key="r1"
    ) is True

    # A still lists nothing, B still lists the shared asset.
    assert domain_assets.list_for_domain(db_conn, domain_key="dom-a")["total"] == 0
    listing_b = domain_assets.list_for_domain(db_conn, domain_key="dom-b")
    assert item_keys(group_of(listing_b, "rubric")) == ["r1"]

    # Directory semantics: the asset row itself is unchanged.
    after = db_conn.execute("SELECT * FROM rubrics WHERE name = 'r1'").fetchone()
    assert after == before
    assert count_rows(db_conn, "SELECT COUNT(*) AS n FROM rubrics") == 1


def test_unassigning_a_never_assigned_key_is_false(db_conn):
    make_domain(db_conn, "dom-a")
    make_rubric(db_conn, "r1")
    assert domain_assets.unassign(
        db_conn, domain_key="dom-a", asset_kind="rubric", asset_key="r1"
    ) is False
    assert count_rows(db_conn, "SELECT COUNT(*) AS n FROM rubrics") == 1


# ------------------------------------------------------------- 校验失败封闭


def test_unknown_kind_and_blank_key_are_refused_naming_the_registry(db_conn):
    make_domain(db_conn, "dom-a")

    with pytest.raises(ValueError, match="rubric"):
        domain_assets.assign(
            db_conn, domain_key="dom-a", asset_kind="book",
            asset_key="b1", added_by="lead-1",
        )
    with pytest.raises(ValueError, match="asset_key"):
        domain_assets.assign(
            db_conn, domain_key="dom-a", asset_kind="rubric",
            asset_key="   ", added_by="lead-1",
        )

    assert count_rows(db_conn, "SELECT COUNT(*) AS n FROM domain_assets") == 0


# ------------------------------------------------------------------- 孤儿行


def test_deleted_asset_becomes_orphan_and_purge_removes_exactly_it(db_conn):
    make_domain(db_conn, "dom-a")
    make_rubric(db_conn, "r1")
    make_prompt(db_conn, "p-gone")
    domain_assets.assign(
        db_conn, domain_key="dom-a", asset_kind="rubric",
        asset_key="r1", added_by="lead-1",
    )
    domain_assets.assign(
        db_conn, domain_key="dom-a", asset_kind="prompt",
        asset_key="p-gone", added_by="lead-1",
    )

    # The asset disappears independently of the directory.
    db_conn.execute("DELETE FROM prompts WHERE name = 'p-gone'")
    db_conn.commit()

    listing = domain_assets.list_for_domain(db_conn, domain_key="dom-a")
    assert listing["total"] == 2
    orphan = group_of(listing, "prompt")["items"][0]
    assert orphan["asset_key"] == "p-gone"
    assert orphan["exists"] is False
    # Display name falls back to the key when the asset is gone.
    assert orphan["name"] == "p-gone"
    assert group_of(listing, "rubric")["items"][0]["exists"] is True

    assert domain_assets.purge_orphans(db_conn, domain_key="dom-a") == 1

    after = domain_assets.list_for_domain(db_conn, domain_key="dom-a")
    assert after["total"] == 1
    assert item_keys(group_of(after, "rubric")) == ["r1"]
    assert group_of(after, "prompt") is None


# --------------------------------------------------------------- 未归属池


def test_unassigned_pool_excludes_any_domain_and_filters_by_kind(db_conn):
    make_domain(db_conn, "dom-a")
    make_domain(db_conn, "dom-b")
    make_rubric(db_conn, "r1")
    make_rubric(db_conn, "r2")
    make_prompt(db_conn, "p1")
    make_prompt(db_conn, "p2")
    make_compare(db_conn, "cmp-1")
    domain_assets.assign(
        db_conn, domain_key="dom-a", asset_kind="rubric",
        asset_key="r1", added_by="lead-1",
    )
    # Assigned to a *different* domain: still not part of the pool.
    domain_assets.assign(
        db_conn, domain_key="dom-b", asset_kind="prompt",
        asset_key="p1", added_by="lead-1",
    )

    pool = domain_assets.list_unassigned(db_conn, domain_key="dom-a")
    assert item_keys(group_of(pool, "rubric")) == ["r2"]
    assert item_keys(group_of(pool, "prompt")) == ["p2"]
    assert item_keys(group_of(pool, "compare")) == ["1"]
    assert all(item["exists"] is True for g in pool["groups"] for item in g["items"])

    only_rubrics = domain_assets.list_unassigned(
        db_conn, domain_key="dom-a", asset_kind="rubric"
    )
    assert [g["kind"] for g in only_rubrics["groups"]] == ["rubric"]
    assert item_keys(group_of(only_rubrics, "rubric")) == ["r2"]

    with pytest.raises(ValueError, match="rubric"):
        domain_assets.list_unassigned(
            db_conn, domain_key="dom-a", asset_kind="book"
        )


# ------------------------------------------------------------------ 回填


def test_backfill_is_idempotent_and_reports_missing_keys(db_conn):
    make_domain(db_conn, "dom-a")
    make_rubric(db_conn, "r1")
    make_rubric(db_conn, "r2")

    first = domain_assets.backfill(
        db_conn, domain_key="dom-a", asset_kind="rubric",
        asset_keys=["r1", "r2", "ghost"], added_by="backfill-script",
    )
    second = domain_assets.backfill(
        db_conn, domain_key="dom-a", asset_kind="rubric",
        asset_keys=["r1", "r2", "ghost"], added_by="backfill-script",
    )

    assert first == {"assigned": 2, "already": 0, "missing": ["ghost"]}
    assert second == {"assigned": 0, "already": 2, "missing": ["ghost"]}
    assert count_rows(db_conn, "SELECT COUNT(*) AS n FROM domain_assets") == 2
    assert item_keys(
        group_of(domain_assets.list_for_domain(db_conn, domain_key="dom-a"), "rubric")
    ) == ["r1", "r2"]


def test_each_kind_resolves_its_own_identity_column(db_conn):
    make_domain(db_conn, "dom-a")
    make_rubric(db_conn, "r1")
    make_prompt(db_conn, "p1")
    compare_id = make_compare(db_conn, "cmp-1")
    make_sample(db_conn, "sha-1", scenario="renewal")
    make_law_info(db_conn, "software")
    # law_info has one row per (contract_type, source); the directory keys the
    # type, so a second source must not duplicate the entry.
    make_law_info(db_conn, "software", source="local")
    clause_id = make_clause(db_conn, "付款")

    keys = {
        "rubric": "r1",
        "prompt": "p1",
        "compare": str(compare_id),
        "sample": "sha-1",
        "clause": str(clause_id),
        "law_info": "software",
    }
    for kind, key in keys.items():
        domain_assets.assign(
            db_conn, domain_key="dom-a", asset_kind=kind,
            asset_key=key, added_by="lead-1",
        )

    listing = domain_assets.list_for_domain(db_conn, domain_key="dom-a")
    assert [g["kind"] for g in listing["groups"]] == list(domain_assets.ASSET_KINDS)
    assert listing["total"] == len(domain_assets.ASSET_KINDS)
    for kind, key in keys.items():
        assert item_keys(group_of(listing, kind)) == [key]
        assert group_of(listing, kind)["items"][0]["exists"] is True
    assert group_of(listing, "compare")["items"][0]["name"] == "cmp-1"


# ------------------------------------------------------------------ 行形状


def test_dict_and_tuple_rows_are_both_decoded(db_conn):
    """The module borrows whichever cursor shape the caller has."""
    make_domain(db_conn, "dom-a")
    make_rubric(db_conn, "r1")

    # empty_db uses dict_row; open a plain tuple-row connection to the same DB.
    tuple_conn = psycopg.connect(os.environ["database_url"])
    try:
        row = domain_assets.assign(
            tuple_conn, domain_key="dom-a", asset_kind="rubric",
            asset_key="r1", added_by="lead-1",
        )
        assert row["asset_key"] == "r1"
        assert row["domain_id"] == domain_assets._load_domain(
            db_conn, domain_key="dom-a"
        )["id"]
        listing = domain_assets.list_for_domain(tuple_conn, domain_key="dom-a")
        assert group_of(listing, "rubric")["items"] == [
            {"asset_key": "r1", "name": "r1", "exists": True}
        ]
    finally:
        tuple_conn.close()


# ------------------------------------------------------- 评测执行路径隔离


def test_domain_assets_is_not_imported_anywhere_in_the_eval_path():
    """The directory must never be consulted by evaluation execution."""
    protected = sorted((REPO_ROOT / "src" / "eval").rglob("*.py")) + [
        REPO_ROOT / "src" / "bench" / "tiers.py",
        REPO_ROOT / "src" / "bench" / "data_checks.py",
    ]
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in protected
        if "domain_assets" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        "evaluation path must not reference the domain catalog: " + repr(offenders)
    )
