"""提案结局回流 + 迁移计数读面（add-fleet-execution-loop §4 / §2.4）。

这两条读面的存在理由不同，但都把「事实」摆到能被核对的位置：

- **结局回流**：提交方必须能读到它的提案怎么结的、为什么。没有这一面，被驳回的
  草案只能靠下一轮再撞一次去重才发现——而「为什么」永远读不到。
- **迁移计数**：宽松窗口结束的依据是一个数，不是一个感觉。数到零才翻硬档。

隔离是这两条的重点：结局按来源读，来源必须经判定等于调用者；计数只给平台管理员。
"""

from __future__ import annotations

import pytest

from src.bench import distribution, proposals, submitters, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from tests._fleet_fixtures import register_fleet


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    schema = {
        "entity_types": ["company"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    templates.create_template(conn=empty_db, name="tpl", schema=schema, created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    register_fleet(empty_db, "fleet_a", ["legal"])
    register_fleet(empty_db, "fleet_b", ["legal"])
    yield empty_db


def _submit(conn, *, source="fleet:fleet_a/p1", key="k1", quote="q", **kw):
    return proposals.submit(
        conn, domain_key="legal", source=source, kind="company", external_key=key,
        body="b", evidence={"quote": quote}, submitted_by=source, **kw
    )


# ------------------------------------------------------------------ outcomes


def test_submitter_reads_its_own_rejection_reason(conn):
    p = _submit(conn)
    proposals.reject(conn, domain_key="legal", proposal_id=p["id"],
                     actor="lead-1", note="依据无法回源")

    rows = proposals.list_outcomes(conn, source="fleet:fleet_a/p1", domain_key="legal")
    assert len(rows) == 1
    assert rows[0]["state"] == "rejected"
    assert rows[0]["decision_note"] == "依据无法回源"
    assert rows[0]["domain_key"] == "legal"


def test_a_second_submitter_cannot_read_the_others_rows(conn):
    _submit(conn, source="fleet:fleet_a/p1")
    assert proposals.list_outcomes(conn, source="fleet:fleet_b/p9", domain_key="legal") == []


def test_a_shared_claim_is_visible_to_both_submitters(conn):
    """同一主张两位提交方合并成一行时，两边都该看得到结局。"""
    _submit(conn, source="fleet:fleet_a/p1")
    _submit(conn, source="fleet:fleet_b/p2")  # same key + same evidence -> one row

    for who in ("fleet:fleet_a/p1", "fleet:fleet_b/p2"):
        rows = proposals.list_outcomes(conn, source=who, domain_key="legal")
        assert len(rows) == 1, who


def test_outcomes_are_scoped_to_the_domain(conn):
    _submit(conn)
    assert proposals.list_outcomes(
        conn, source="fleet:fleet_a/p1", domain_key="gov"
    ) == []


def test_source_is_required(conn):
    with pytest.raises(ValueError, match="source is required"):
        proposals.list_outcomes(conn, source="  ")


# ----------------------------------------------------------- legacy counting


def test_legacy_zero_while_everything_passes(conn):
    _submit(conn)
    assert proposals.legacy_sources(conn) == []


def test_lenient_window_counts_by_source(conn, monkeypatch):
    monkeypatch.setenv("BENCH_SUBMITTER_MODE", proposals.MODE_LENIENT)
    # ``user:`` from an in-process call has no authenticated identity to match,
    # so it is recorded but classified as a mismatch.
    proposals.submit(
        conn, domain_key="legal", source="user:someone@example.com", kind="company",
        external_key="k2", body="b", evidence={"quote": "q"},
        submitted_by="someone@example.com",
    )
    rows = proposals.legacy_sources(conn)
    assert rows and rows[0]["source"] == "user:someone@example.com"
    assert rows[0]["verdict"] == "user_mismatch"

    assert proposals.legacy_sources(conn, verdict="user_mismatch") == rows
    assert proposals.legacy_sources(conn, verdict="unregistered") == []


def test_lenient_window_never_admits_pipeline_impersonation(conn, monkeypatch):
    """宽松档只放过历史遗留，不放过冒充——那是伪造，不是迁移。"""
    monkeypatch.setenv("BENCH_SUBMITTER_MODE", proposals.MODE_LENIENT)
    with pytest.raises(proposals.SubmitterRefused) as exc:
        proposals.submit(
            conn, domain_key="legal", source="extract:m:v", kind="company",
            external_key="k3", body="b", evidence={"quote": "q"},
            submitted_by="x", via=submitters.VIA_HTTP,
        )
    assert exc.value.verdict == "pipeline_impersonation"
    assert conn.execute("SELECT count(*) AS n FROM domain_proposals").fetchone()["n"] == 0


def test_strict_is_the_default(conn, monkeypatch):
    monkeypatch.delenv("BENCH_SUBMITTER_MODE", raising=False)
    assert proposals._submitter_mode() == proposals.MODE_STRICT
    with pytest.raises(proposals.SubmitterRefused):
        _submit(conn, source="user:someone@example.com")


# ------------------------------------------------------- verdict is persisted


def test_verdict_is_recorded_on_the_row(conn):
    _submit(conn)
    verdict = conn.execute(
        "SELECT submitter_verdict FROM domain_proposals"
    ).fetchone()["submitter_verdict"]
    assert verdict == "ok"


def test_resolve_submitter_authorizes_the_owner_only(conn):
    """路由的隔离依据：同一个 source，换一个认证身份就不匹配。"""
    _, ok = distribution.resolve_submitter(
        conn, source="user:alice@example.com", domain_key="legal",
        via=submitters.VIA_HTTP, authenticated_as="alice@example.com",
    )
    _, bad = distribution.resolve_submitter(
        conn, source="user:alice@example.com", domain_key="legal",
        via=submitters.VIA_HTTP, authenticated_as="bob@example.com",
    )
    assert (ok, bad) == ("ok", "user_mismatch")
