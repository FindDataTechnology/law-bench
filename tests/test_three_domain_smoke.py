"""Three-domain integration smoke (task 7.1).

One module, three domains, one honest round each:

- legal (packs/legal): real clause-seed load -> tag-driven assembly ->
  rubric evaluation (FakeJudge, hermetic) -> double-slot blind review batch
  created, every task decided, stats confirm the batch closed.
- finance-data: read-only gold-v9 load (idempotent) -> deterministic data
  channel run_data_eval -> honest per-checker verdict rows; data-QA goldset
  built from real truth with executable judges.
- gov: registry load (idempotent) -> deterministic data channel -> all
  criteria PASS.

The one-off md record lives in the change dir; this module is the repeatable
smoke (CI runs it on every push).
"""

from __future__ import annotations

import importlib

import pytest

from _fakes import FakeJudge

from src.clauses.assemble import generate_contract_assembled
from src.clauses.store import upsert_clause
from src.eval.review import batch_stats, create_batch, decide_task
from src.eval.scoring import evaluate_contract
from src.eval.store import ensure_schema, store_result

_RUBRIC = "h_rubric"  # seeded by conftest seed_db


def test_legal_chain_assemble_eval_review(seeded_db):
    # assembly over the real clause store (pattern proven by
    # tests/test_clauses_assemble.py's own seeds)
    upsert_clause(
        {
            "contract_type": "sale", "category": "base", "section": "当事人",
            "body": "甲方：{{party_a}}；乙方：{{party_b}}（base-marker）",
            "slot_instructions": [
                {"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True},
                {"name": "party_b", "label": "乙方", "description": "d", "example": "y", "required": True},
            ],
            "law_refs": [], "tags": {}, "level": "national",
            "source_path": "t/smoke-base.docx", "source_doc_title": "T",
            "body_hash": "smoke-b1",
        },
        db=seeded_db,
    )
    upsert_clause(
        {
            "contract_type": "sale", "category": "base", "section": "违约责任",
            "body": "违约方应按违约金{{penalty}}承担赔偿责任，不得以损失轻微为由免除。",
            "slot_instructions": [
                {"name": "penalty", "label": "违约金", "description": "d", "example": "10%", "required": False},
            ],
            "law_refs": [], "tags": {}, "level": "national",
            "source_path": "t/smoke-base2.docx", "source_doc_title": "T",
            "body_hash": "smoke-b2",
        },
        db=seeded_db,
    )
    draft = generate_contract_assembled("sale", format="markdown", db=seeded_db)
    body = draft["body_text"] or ""
    assert "base-marker" in body and "违约责任" in body, "assembled body missing seeded clauses"

    n_crit = seeded_db.execute(
        "SELECT count(*) AS n FROM criteria c JOIN rubrics r ON r.id=c.rubric_id "
        "WHERE r.name = %s",
        (_RUBRIC,),
    ).fetchone()["n"]
    result = evaluate_contract(
        body,
        _RUBRIC,
        judge=FakeJudge(verdicts=[True] * n_crit),
        max_workers=1,
        db_path=seeded_db,
    )
    assert result["n_criteria"] == n_crit
    run_id = store_result(result, db_path=seeded_db)
    ids = [
        r["id"]
        for r in seeded_db.execute(
            "SELECT id FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal",
            (run_id,),
        ).fetchall()
    ]

    batch = create_batch(
        batch_id="smoke-legal-7-1",
        batch_type="validity",
        eval_criteria_result_ids=ids,
        annotators=2,
        db=seeded_db,
    )
    assert batch["total"] == 2 * len(ids) > 0
    pending = seeded_db.execute(
        "SELECT id, slot FROM review_tasks WHERE batch_id = %s AND status = 'pending'",
        ("smoke-legal-7-1",),
    ).fetchall()
    assert len(pending) == batch["total"]
    for t in pending:
        decide_task(
            task_id=t["id"], verdict="pass", annotator=f"smoke-slot-{t['slot']}",
            db=seeded_db,
        )
    stats = batch_stats("smoke-legal-7-1", db=seeded_db)
    decided_rows = stats["by_annotator"]
    assert sum(r["decided"] for r in decided_rows) == batch["total"] > 0
    assert sum(r["positive"] for r in decided_rows) == batch["total"]  # all pass


def test_finance_data_chain_load_eval_goldset(empty_db):
    adapters_probe = importlib.import_module("packs.finance-data.adapters")
    gold = adapters_probe.sentiment_repo() / adapters_probe.GOLD_REL
    if not gold.is_file():
        pytest.skip(f"fd-sentiment goldset absent at {gold} - smoke not runnable here")
    ensure_schema(db_path=empty_db)
    adapters = adapters_probe
    checks = importlib.import_module("packs.finance-data.checks")  # registers checkers
    from src.bench.data_checks import checkers_for, run_data_eval
    from src.bench.store import list_knowledge_units

    loaded = adapters.load_sentiment_gold(empty_db)
    assert loaded > 0
    assert adapters.load_sentiment_gold(empty_db) == loaded  # idempotent
    units = list_knowledge_units(
        empty_db, kind="fact", namespace="finance-data", limit=1000
    )
    assert len(units) == loaded

    n_checkers = len(checkers_for("fact"))
    assert n_checkers >= 3
    run_id = run_data_eval(empty_db, kind="fact", db_path=empty_db)
    row = empty_db.execute(
        "SELECT channel, unit_kind, n_criteria, n_passed FROM eval_runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    assert row["channel"] == "data" and row["unit_kind"] == "fact"
    assert row["n_criteria"] == loaded * n_checkers

    questions = checks.build_data_qa_goldset(adapters.read_gold_records())
    assert len(questions) >= 5
    units_by_key = {u["external_key"]: u for u in units}
    for q in questions:
        assert q["judge"] in checks.JUDGE_FUNCS
        # the named judge executes on the stored unit against the question
        assert checks.JUDGE_FUNCS[q["judge"]](units_by_key[q["unit_key"]], q)


def test_gov_chain_load_eval(empty_db):
    # 政务语料在本仓的兄弟仓里（只读），本仓 clone 里没有它——缺了要如实 skip，
    # 否则出片闸门在任何干净 runner 上永远红（2026-11-11 实测：CI 因家目录路径失败）。
    from packs.gov import adapters as _gov_adapters

    if not _gov_adapters.registry_path().is_file():
        pytest.skip(f"fd-cn-gov registry absent at {_gov_adapters.registry_path()} - smoke not runnable here")
    ensure_schema(db_path=empty_db)
    adapters = importlib.import_module("packs.gov.adapters")
    checks = importlib.import_module("packs.gov.checks")  # registers checkers
    from src.bench.data_checks import checkers_for, run_data_eval
    from src.bench.store import list_knowledge_units

    loaded = adapters.load_gov_registry(empty_db)
    assert loaded > 0
    assert adapters.load_gov_registry(empty_db) == loaded
    units = list_knowledge_units(empty_db, kind="gov-fact", namespace="gov", limit=100)
    assert len(units) == loaded

    n_checkers = len(checkers_for("gov-fact"))
    assert n_checkers >= 4
    run_id = run_data_eval(empty_db, kind="gov-fact", db_path=empty_db)
    row = empty_db.execute(
        "SELECT channel, unit_kind, n_criteria, n_passed, all_pass "
        "FROM eval_runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    assert row["channel"] == "data" and row["unit_kind"] == "gov-fact"
    assert row["n_criteria"] == loaded * n_checkers
    assert row["all_pass"] == 1  # real registry honestly passes every check
