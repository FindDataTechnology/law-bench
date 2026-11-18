"""概念岗：只提案，绝不落库。

这一岗要钉的是"判断权留在人手上"：

- 产出只有 `pending` 提案，`knowledge_units` 一行都不能多；
- 每批必须带摘要（共同主张 / 类型分布 / 被哪个闸门拒掉多少），没有摘要的批
  没法按批复核；
- 薄产判 `thin` 并升级给人，不重跑（加量只会放大噪声）；
- 失败仍留台账。
"""

from __future__ import annotations

import json

import pytest

import packs.legal  # noqa: F401
from src.bench import agent_runs, extraction, proposals, team_roles, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

SCHEMA = {
    "entity_types": ["clause", "law", "concept"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["defines"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}

CHUNK = "第一条 为了规范合同的订立，制定本法。第二条 合同应当采用书面形式。"
AGENT = "agent:concept@legal"


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS rubrics (id BIGINT GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, name TEXT NOT NULL, context TEXT, source TEXT, source_path TEXT, "
        "description TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.commit()
    from src.eval import store as eval_store
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _with_corpus(conn, monkeypatch, text: str = CHUNK):
    """装一个单块的语料面（qz 用 fake post，走 extraction 的采样路径）。"""
    from src.bench import libraries
    from src.search import library_index

    libraries.create_library(
        conn, library_key="law-library", name="law-library", created_by="t",
        backend="qdrant", embedding_model="m", dims=1024,
        location={"url_env": "TEST_QDRANT_URL", "collection": "corpus"})
    libraries.add_source(
        conn, library_key="law-library", source_key="statutes",
        uri="collection:corpus/statutes", created_by="t", source_kind="payload-filter",
        ingest_rule={"match": {"category": ["statutes"]}})
    dom = conn.execute("SELECT id FROM domains WHERE key='legal'").fetchone()
    libraries.subscribe(conn, domain_id=dom["id"], library_key="law-library", created_by="t")
    conn.commit()

    import httpx

    def post(url, path, body, timeout=30.0):
        points = [{"id": "c1", "payload": {"chunk_text": text, "category": "statutes",
                                           "title": "中华人民共和国合同法", "law_id": 1,
                                           "chunk_no": 0}}]
        return {"result": {"points": points, "next_page_offset": None}}

    monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")
    monkeypatch.setattr(extraction, "_post", post)
    return dom


def _answer(**over):
    row = {"entities": [{"kind": "concept", "name": "违约金调整", "chunk_id": "c1",
                         "quote": "合同应当采用书面形式"}], "relationships": []}
    row.update(over)
    return json.dumps(row, ensure_ascii=False)


# ── 只提案 ──────────────────────────────────────────────────────────────────


def test_concept_role_files_proposals_and_writes_no_units(conn, monkeypatch):
    _with_corpus(conn, monkeypatch)
    before = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    out = team_roles.run_concept(conn, domain_key="legal", max_chunks=1,
                                 batch="b1", complete_fn=lambda p: _answer())
    after = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    assert after == before, "概念岗不得写任何单位"
    assert out["submitted"] >= 1
    rows = proposals.list_proposals(conn, domain_key="legal", state="pending")
    assert [r["external_key"] for r in rows] == ["违约金调整"]


def test_every_proposal_is_pending_not_confirmed(conn, monkeypatch):
    _with_corpus(conn, monkeypatch)
    team_roles.run_concept(conn, domain_key="legal", max_chunks=1,
                           batch="b2", complete_fn=lambda p: _answer())
    states = {r["state"] for r in conn.execute(
        "SELECT state FROM domain_proposals").fetchall()}
    assert states == {"pending"}


def test_the_batch_carries_a_summary(conn, monkeypatch):
    _with_corpus(conn, monkeypatch)
    out = team_roles.run_concept(conn, domain_key="legal", max_chunks=1,
                                 batch="b3", complete_fn=lambda p: _answer())
    assert "b3" in out["summary"]
    assert "采样 1 块" in out["summary"]
    assert "concept×1" in out["summary"]
    assert out["run"]["detail"] == out["summary"], "摘要要随台账落库，复核才有依据"


def test_the_summary_names_what_the_gates_rejected(conn, monkeypatch):
    _with_corpus(conn, monkeypatch)
    # 引文不在原文里 → bad_quote
    bad = json.dumps({"entities": [{"kind": "concept", "name": "某个概念",
                                    "chunk_id": "c1", "quote": "这句不在原文里"}],
                      "relationships": []}, ensure_ascii=False)
    out = team_roles.run_concept(conn, domain_key="legal", max_chunks=1,
                                 batch="b4", complete_fn=lambda p: bad)
    assert "bad_quote×1" in out["summary"]


# ── 薄产即停 ────────────────────────────────────────────────────────────────


def test_empty_output_is_thin_not_a_silent_success(conn, monkeypatch):
    _with_corpus(conn, monkeypatch)
    out = team_roles.run_concept(
        conn, domain_key="legal", max_chunks=1, batch="b5",
        complete_fn=lambda p: json.dumps({"entities": [], "relationships": []}))
    assert out["submitted"] == 0
    assert out["run"]["outcome"] == "thin"


def test_low_usable_rate_is_thin(conn, monkeypatch):
    _with_corpus(conn, monkeypatch)
    # 一条对（引文逐字）、一条错（引文编造）→ 可用率 0.5 恰好不低于 0.5，用更差的
    two_bad = json.dumps({"entities": [
        {"kind": "concept", "name": "甲概念", "chunk_id": "c1", "quote": "编造的一"},
        {"kind": "concept", "name": "乙概念", "chunk_id": "c1", "quote": "编造的二"}],
        "relationships": []}, ensure_ascii=False)
    out = team_roles.run_concept(conn, domain_key="legal", max_chunks=1,
                                 batch="b6", complete_fn=lambda p: two_bad)
    assert out["submitted"] == 0
    assert out["run"]["outcome"] == "thin"


# ── 台账 ────────────────────────────────────────────────────────────────────


def test_concept_run_is_recorded_with_its_batch(conn, monkeypatch):
    _with_corpus(conn, monkeypatch)
    out = team_roles.run_concept(conn, domain_key="legal", max_chunks=1,
                                 batch="b7", complete_fn=lambda p: _answer())
    run = agent_runs.get(conn, run_id=out["run"]["id"])
    assert run["role"] == AGENT
    assert run["run_key"] == "b7"
    assert run["counts"]["batch"] == "b7"
    assert run["artifact_refs"] == [{"batch": "b7"}]


def test_a_failed_concept_run_is_recorded(conn, monkeypatch):
    _with_corpus(conn, monkeypatch)

    def boom(prompt):
        raise RuntimeError("通道挂了")

    with pytest.raises(RuntimeError):
        team_roles.run_concept(conn, domain_key="legal", max_chunks=1,
                               batch="b8", complete_fn=boom)
    rows = agent_runs.list_runs(conn, domain_key="legal", role=AGENT)
    assert rows and rows[0]["outcome"] == "failed"
    assert "通道挂了" in (rows[0]["detail"] or "")
