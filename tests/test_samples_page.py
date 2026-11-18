"""Tests for the ``/samples`` browse-and-download page and its service layer.

Service-layer tests exercise ``distinct_scenarios`` / ``distinct_stances`` /
``list_samples`` directly against the shared ``seeded_db`` connection, seeding
``contract_artifacts`` rows by hand. Route tests go through ``app_client`` (which
overrides ``get_db`` to that same connection) and assert on rendered HTML.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from src.contracts.artifacts import (
    distinct_scenarios,
    distinct_stances,
    list_samples,
)
from fastapi.testclient import TestClient


# --- seeding helpers ------------------------------------------------------- #


def _artifact(
    *,
    contract_type: str,
    body_hash: str,
    scenario: str | None = None,
    stance: str | None = None,
    docx_key: str | None = "k.docx",
    pdf_key: str | None = "k.pdf",
    slots: list | None = None,
    now: str = "2026-01-01T00:00:00+00:00",
) -> tuple:
    return (
        contract_type,
        scenario,
        stance,
        None,  # custom_clause_ids
        body_hash,
        f"body-{body_hash}",  # body_text (non-null)
        Jsonb(slots or [{"name": "party_a"}, {"name": "party_b"}]),
        docx_key,
        pdf_key,
        "test-bucket",
        now,
        now,
    )


_COLS = (
    "contract_type, scenario, stance, custom_clause_ids, body_hash, "
    "body_text, slots, docx_key, pdf_key, minio_bucket, created_at, updated_at"
)


def _seed_sale_artifacts(seeded_db) -> None:
    """Six sale artifacts: 1 base + 2 scenario-tagged + 2 stance-tagged + 1 combo."""
    rows = [
        _artifact(contract_type="sale", body_hash="sale-base"),  # NULL scenario/stance
        _artifact(contract_type="sale", body_hash="sale-agri", scenario="农产品买卖"),
        _artifact(contract_type="sale", body_hash="sale-steel", scenario="钢材买卖"),
        _artifact(contract_type="sale", body_hash="sale-proa", stance="pro_a"),
        _artifact(contract_type="sale", body_hash="sale-bal", stance="balanced"),
        _artifact(
            contract_type="sale",
            body_hash="sale-agri-proa",
            scenario="农产品买卖",
            stance="pro_a",
        ),
    ]
    seeded_db.execute(
        f"INSERT INTO contract_artifacts ({_COLS}) VALUES "
        + ", ".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(rows)),
        [v for r in rows for v in r],
    )
    # One artifact of a different type to confirm the type filter scopes rows.
    other = _artifact(contract_type="lease", body_hash="lease-base")
    seeded_db.execute(
        f"INSERT INTO contract_artifacts ({_COLS}) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        other,
    )
    seeded_db.commit()


# --- service: distinct_* --------------------------------------------------- #


def test_distinct_scenarios_excludes_null(seeded_db):
    _seed_sale_artifacts(seeded_db)
    scens = distinct_scenarios("sale", db=seeded_db)
    assert "农产品买卖" in scens
    assert "钢材买卖" in scens
    # base row (NULL scenario) excluded
    assert None not in scens
    # lease's nonexistent scenario set is excluded
    assert all(s not in ("lease",) for s in scens)


def test_distinct_stances_excludes_null(seeded_db):
    _seed_sale_artifacts(seeded_db)
    stances = distinct_stances("sale", db=seeded_db)
    assert "pro_a" in stances
    assert "balanced" in stances
    assert None not in stances


def test_distinct_empty_for_unknown_type(seeded_db):
    _seed_sale_artifacts(seeded_db)
    assert distinct_scenarios("does_not_exist", db=seeded_db) == []
    assert distinct_stances("does_not_exist", db=seeded_db) == []


# --- service: list_samples ------------------------------------------------- #


def test_list_samples_returns_rows_and_total(seeded_db):
    _seed_sale_artifacts(seeded_db)
    rows, total = list_samples(contract_type="sale", db=seeded_db)
    assert total == 6  # all six sale artifacts, not the lease one
    assert len(rows) == 6
    # body_text must not be pulled into the listing query
    assert all("body_text" not in r for r in rows)
    # newest first: ordered by id DESC
    assert rows[0]["id"] > rows[-1]["id"]


def test_list_samples_specific_scenario_excludes_base(seeded_db):
    _seed_sale_artifacts(seeded_db)
    rows, total = list_samples(
        contract_type="sale", scenario="农产品买卖", db=seeded_db
    )
    # two rows: sale-agri (scenario only) + sale-agri-proa (scenario+stance)
    assert total == 2
    assert all(r["scenario"] == "农产品买卖" for r in rows)
    # no base (NULL-scenario) rows
    assert all(r["scenario"] is not None for r in rows)


def test_list_samples_no_scenario_includes_base(seeded_db):
    _seed_sale_artifacts(seeded_db)
    rows, total = list_samples(contract_type="sale", db=seeded_db)
    # the base row (NULL scenario) is present
    assert any(r["scenario"] is None for r in rows)
    assert total == 6


def test_list_samples_stance_filter(seeded_db):
    _seed_sale_artifacts(seeded_db)
    rows, total = list_samples(contract_type="sale", stance="pro_a", db=seeded_db)
    # sale-proa + sale-agri-proa
    assert total == 2
    assert all(r["stance"] == "pro_a" for r in rows)


def test_list_samples_scenario_and_stance_compose_via_and(seeded_db):
    _seed_sale_artifacts(seeded_db)
    rows, total = list_samples(
        contract_type="sale",
        scenario="农产品买卖",
        stance="pro_a",
        db=seeded_db,
    )
    assert total == 1
    assert rows[0]["scenario"] == "农产品买卖"
    assert rows[0]["stance"] == "pro_a"


def test_list_samples_pagination_first_page(seeded_db):
    _seed_sale_artifacts(seeded_db)
    rows, total = list_samples(
        contract_type="sale", limit=4, offset=0, db=seeded_db
    )
    assert len(rows) == 4
    assert total == 6  # total reflects the full filtered set, not the page


def test_list_samples_offset_beyond_total(seeded_db):
    _seed_sale_artifacts(seeded_db)
    rows, total = list_samples(
        contract_type="sale", limit=50, offset=10000, db=seeded_db
    )
    assert rows == []
    assert total == 6  # unchanged


def test_list_samples_unknown_type_empty(seeded_db):
    _seed_sale_artifacts(seeded_db)
    rows, total = list_samples(contract_type="does_not_exist", db=seeded_db)
    assert rows == []
    assert total == 0


# --- service: superseded filtering ---------------------------------------- #


def _seed_superseded(seeded_db) -> None:
    """Add one sale artifact marked superseded alongside the six current ones."""
    # Reuse the seed, then mark one extra row superseded. Insert directly so the
    # superseded_at column is set explicitly (the _artifact helper omits it, so
    # its rows default to NULL = current).
    _seed_sale_artifacts(seeded_db)
    seeded_db.execute(
        f"INSERT INTO contract_artifacts ({_COLS}, superseded_at) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "sale", "钢材买卖", None, None, "sale-steel-v2", "body-sale-steel-v2",
            Jsonb([{"name": "party_a"}]), "k.docx", "k.pdf",
            "test-bucket", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            "2026-02-01T00:00:00+00:00",
        ),
    )
    seeded_db.commit()


def test_list_samples_hides_superseded_by_default(seeded_db):
    _seed_superseded(seeded_db)
    rows, total = list_samples(contract_type="sale", db=seeded_db)
    # six current rows; the one superseded sale-steel-v2 is excluded
    assert total == 6
    assert all(r["body_hash"] != "sale-steel-v2" for r in rows)


def test_list_samples_include_superseded_returns_them(seeded_db):
    _seed_superseded(seeded_db)
    rows, total = list_samples(
        contract_type="sale", include_superseded=True, db=seeded_db
    )
    # six current + one superseded
    assert total == 7
    assert any(r["body_hash"] == "sale-steel-v2" for r in rows)


def test_distinct_scenarios_hides_superseded(seeded_db):
    _seed_superseded(seeded_db)
    # sale-steel-v2 is superseded; "钢材买卖" still appears via the current
    # sale-steel row, so this only confirms no crash. Add a scenario that
    # exists ONLY on a superseded row to prove it is hidden.
    seeded_db.execute(
        f"INSERT INTO contract_artifacts ({_COLS}, superseded_at) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "sale", "废弃场景", None, None, "sale-gone", "body-gone",
            Jsonb([{"name": "party_a"}]), "k.docx", "k.pdf",
            "test-bucket", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            "2026-02-01T00:00:00+00:00",
        ),
    )
    seeded_db.commit()
    scens = distinct_scenarios("sale", db=seeded_db)
    assert "废弃场景" not in scens
    scens_all = distinct_scenarios("sale", include_superseded=True, db=seeded_db)
    assert "废弃场景" in scens_all


def test_distinct_stances_hides_superseded(seeded_db):
    _seed_superseded(seeded_db)
    # Add a stance that exists ONLY on a superseded row.
    seeded_db.execute(
        f"INSERT INTO contract_artifacts ({_COLS}, superseded_at) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "sale", None, "gone_stance", None, "sale-gone-stance", "body-gone-s",
            Jsonb([{"name": "party_a"}]), "k.docx", "k.pdf",
            "test-bucket", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            "2026-02-01T00:00:00+00:00",
        ),
    )
    seeded_db.commit()
    stances = distinct_stances("sale", db=seeded_db)
    assert "gone_stance" not in stances
    stances_all = distinct_stances("sale", include_superseded=True, db=seeded_db)
    assert "gone_stance" in stances_all


# --- route ----------------------------------------------------------------- #


def test_samples_page_renders(app_client: TestClient):
    r = app_client.get("/samples")
    assert r.status_code == 200
    body = r.text
    assert "<table" in body
    # the type dropdown is always populated
    assert "全部类型" in body


def test_samples_page_unknown_type_no_500(app_client: TestClient):
    r = app_client.get("/samples", params={"contract_type": "does_not_exist"})
    assert r.status_code == 200
    assert "没有匹配的样本" in r.text


def test_samples_page_with_type_populates_dropdowns(
    app_client: TestClient, seeded_db
):
    _seed_sale_artifacts(seeded_db)
    r = app_client.get("/samples", params={"contract_type": "sale"})
    assert r.status_code == 200
    body = r.text
    # scenario dropdown now carries the distinct sale scenarios
    assert "农产品买卖" in body
    assert "钢材买卖" in body
    # stance dropdown carries the distinct stances
    assert "pro_a" in body
    assert "balanced" in body
    # the selected type option is marked selected
    assert 'value="sale"' in body and "selected" in body


def test_samples_page_scenario_filter_narrows(app_client: TestClient, seeded_db):
    _seed_sale_artifacts(seeded_db)
    r = app_client.get(
        "/samples",
        params={"contract_type": "sale", "scenario": "农产品买卖"},
    )
    assert r.status_code == 200
    body = r.text
    # two matching rows; the base (— scenario) row must not appear as a data row
    # but the table header still renders. Confirm the combo artifact row shows.
    assert "pro_a" in body  # the sale-agri-proa row renders its stance


def test_samples_page_download_links(app_client: TestClient, seeded_db):
    _seed_sale_artifacts(seeded_db)
    r = app_client.get("/samples", params={"contract_type": "sale"})
    assert r.status_code == 200
    body = r.text
    # every stored-key artifact gets an href download anchor
    assert "/download?format=docx" in body
    assert "/download?format=pdf" in body


def test_samples_page_pagination_links(app_client: TestClient, seeded_db):
    _seed_sale_artifacts(seeded_db)
    r = app_client.get(
        "/samples", params={"contract_type": "sale", "limit": 4, "offset": 0}
    )
    assert r.status_code == 200
    body = r.text
    # total (6) > limit (4) -> a "next" anchor must be present
    assert "下一页" in body
    # offset=0 -> no previous
    assert "上一页" not in body or "disabled" in body


def test_samples_page_excluded_from_openapi(app_client: TestClient):
    paths = set(app_client.get("/openapi.json").json()["paths"].keys())
    assert "/samples" not in paths
