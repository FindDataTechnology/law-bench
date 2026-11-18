"""Unit tests for ``src/eval/store.py`` against a throwaway Postgres DB."""

from __future__ import annotations

import pytest

from src.eval.store import (
    ensure_schema,
    get_compare,
    get_run,
    get_run_draft,
    list_compares,
    list_runs,
    store_compare,
    store_result,
)


def _result(rubric: str = "r", all_pass: bool = False, n: int = 2, n_passed: int = 1) -> dict:
    return {
        "rubric": rubric,
        "score": 1.0 if all_pass else 0.0,
        "max_score": 1.0,
        "all_pass": all_pass,
        "n_criteria": n,
        "n_passed": n_passed,
        "summary": "s",
        "judge_model": "fake-judge",
        "scored_at": "2026-01-01T00:00:00+00:00",
        "criteria_results": [
            {"id": "c1", "title": "t1", "verdict": "pass", "reasoning": "ok"},
            {"id": "c2", "title": "t2", "verdict": "fail", "reasoning": "no"},
        ],
    }


def test_ensure_schema_idempotent(seeded_db):
    ensure_schema(seeded_db)
    ensure_schema(seeded_db)  # second call must not error
    names = {
        r["table_name"]
        for r in seeded_db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        ).fetchall()
    }
    assert {"eval_runs", "eval_criteria_results"} <= names


def test_store_result_round_trip(seeded_db):
    rid = store_result(_result(), contract_path="out.md", task_desc="起草", db_path=seeded_db)
    assert isinstance(rid, int)
    runs = list_runs(db_path=seeded_db)
    assert len(runs) == 1
    run = runs[0]
    assert run["id"] == rid
    assert run["rubric_name"] == "r"
    assert run["score"] == 0.0
    assert run["all_pass"] == 0
    assert run["n_passed"] == 1
    assert run["n_criteria"] == 2
    assert run["contract_path"] == "out.md"


def test_list_runs_newest_first(seeded_db):
    id1 = store_result(_result(rubric="r1"), db_path=seeded_db)
    id2 = store_result(_result(rubric="r2"), db_path=seeded_db)
    id3 = store_result(_result(rubric="r3"), db_path=seeded_db)
    runs = list_runs(db_path=seeded_db)
    assert [r["id"] for r in runs] == [id3, id2, id1]


def test_store_result_persists_criteria_verdicts(seeded_db):
    rid = store_result(_result(), db_path=seeded_db)
    rows = seeded_db.execute(
        "SELECT criterion_id, verdict FROM eval_criteria_results "
        "WHERE run_id = %s ORDER BY ordinal",
        (rid,),
    ).fetchall()
    assert [(r["criterion_id"], r["verdict"]) for r in rows] == [
        ("c1", "pass"),
        ("c2", "fail"),
    ]


def test_get_run_returns_fields_and_criteria(seeded_db):
    rid = store_result(_result(), contract_path="out.md", task_desc="起草", db_path=seeded_db)
    run = get_run(rid, db_path=seeded_db)
    assert run["id"] == rid
    assert run["rubric_name"] == "r"
    assert run["contract_path"] == "out.md"
    assert run["task_desc"] == "起草"
    assert run["n_passed"] == 1 and run["n_criteria"] == 2
    assert [c["criterion_id"] for c in run["criteria_results"]] == ["c1", "c2"]
    assert run["criteria_results"][0]["verdict"] == "pass"


def test_get_run_unknown_id_raises(seeded_db):
    with pytest.raises(KeyError):
        get_run(999999, db_path=seeded_db)


# --- compare persistence + migration --------------------------------------- #


def _result_with_criteria(rubric="r", verdicts=(("c1", "pass"), ("c2", "fail"))) -> dict:
    return {
        "rubric": rubric,
        "score": 0.0,
        "max_score": 1.0,
        "all_pass": False,
        "n_criteria": len(verdicts),
        "n_passed": sum(1 for _, v in verdicts if v == "pass"),
        "summary": "s",
        "judge_model": "fake-judge",
        "scored_at": "2026-01-01T00:00:00+00:00",
        "criteria_results": [
            {"id": cid, "title": f"t-{cid}", "verdict": v, "reasoning": "r"}
            for cid, v in verdicts
        ],
    }


def test_store_result_standalone_keeps_compare_cols_null(seeded_db):
    """Standalone (non-compare) runs store with all compare columns null."""
    rid = store_result(_result_with_criteria(), db_path=seeded_db)
    row = seeded_db.execute(
        "SELECT compare_run_id, prompt_name, prompt_type, variant_label, draft_text "
        "FROM eval_runs WHERE id = %s",
        (rid,),
    ).fetchone()
    assert row["compare_run_id"] is None
    assert row["prompt_name"] is None
    assert row["draft_text"] is None


def test_store_compare_round_trip(seeded_db):
    cid = store_compare("sale test", "sale", "contract_sale_v1", "task", "drafter-only", 1, db_path=seeded_db)
    rid = store_result(
        _result_with_criteria(),
        task_desc="task",
        db_path=seeded_db,
        compare_run_id=cid,
        prompt_name="draft_sale",
        prompt_type="baseline",
        variant_label="baseline",
        draft_text="DRAFT",
    )
    assert isinstance(cid, int) and isinstance(rid, int)

    comps = list_compares(db_path=seeded_db)
    assert len(comps) == 1 and comps[0]["id"] == cid

    got = get_compare(cid, db_path=seeded_db)
    assert got["id"] == cid
    assert got["runs"][0]["prompt_name"] == "draft_sale"
    assert got["runs"][0]["prompt_type"] == "baseline"
    assert "draft_text" not in got["runs"][0]  # excluded from default payload

    d = get_run_draft(cid, rid, db_path=seeded_db)
    assert d["draft_text"] == "DRAFT"


def test_get_compare_survives_prompt_deletion(seeded_db):
    """Snapshotted prompt metadata survives deletion of the prompt row (no FK)."""
    cid = store_compare("lbl", "sale", "contract_sale_v1", "task", "drafter-only", 1, db_path=seeded_db)
    store_result(
        _result_with_criteria(),
        db_path=seeded_db,
        compare_run_id=cid,
        prompt_name="draft_sale",
        prompt_type="baseline",
        variant_label="baseline",
        draft_text="DRAFT",
    )
    # There is no prompts row in this fixture; the snapshot stands on its own.
    got = get_compare(cid, db_path=seeded_db)
    assert got["runs"][0]["prompt_name"] == "draft_sale"
    assert got["runs"][0]["prompt_type"] == "baseline"


def test_get_run_draft_rejects_wrong_compare(seeded_db):
    cid = store_compare("lbl", "sale", "contract_sale_v1", "task", "drafter-only", 1, db_path=seeded_db)
    rid = store_result(
        _result_with_criteria(), db_path=seeded_db, compare_run_id=cid, prompt_name="p",
    )
    with pytest.raises(KeyError):
        get_run_draft(cid + 999, rid, db_path=seeded_db)  # run belongs to a different compare


def test_migration_adds_columns_to_old_eval_runs(empty_db):
    """An eval_runs table created pre-change (no compare cols) is migrated in place."""
    # Old shape: eval_runs without the compare-driven columns. (PostgreSQL
    # INTEGER PRIMARY KEY does not auto-generate, so insert an explicit id.)
    empty_db.execute(
        "CREATE TABLE eval_runs (id INTEGER PRIMARY KEY, rubric_name TEXT, score REAL)"
    )
    empty_db.execute("INSERT INTO eval_runs (id, rubric_name, score) VALUES (1, 'r', 0.0)")
    empty_db.commit()

    ensure_schema(empty_db)  # should ALTER the existing table
    cols = {
        r["column_name"]
        for r in empty_db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'eval_runs'"
        ).fetchall()
    }
    assert {"compare_run_id", "prompt_name", "prompt_type", "variant_label", "draft_text"} <= cols
    # existing row's new columns are null
    row = empty_db.execute(
        "SELECT compare_run_id, draft_text FROM eval_runs WHERE id = 1"
    ).fetchone()
    assert row["compare_run_id"] is None and row["draft_text"] is None

    ensure_schema(empty_db)  # idempotent: no error on second run
    assert {"compare_run_id", "draft_text"} <= cols


def test_migration_creates_compare_runs_table(seeded_db):
    ensure_schema(seeded_db)
    tables = {
        r["table_name"]
        for r in seeded_db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    }
    assert "compare_runs" in tables


def test_ensure_schema_survives_clauses_already_migrated(empty_db):
    """Regression: ensure_schema must be idempotent when clauses.category/level/
    province were already dropped (the post-unify-clause-tags production state).

    The additive migration used to run ``ALTER COLUMN category DROP NOT NULL``
    before ``DROP COLUMN IF EXISTS category``; the ALTER has no column-level
    ``IF EXISTS`` guard, so it errored on any DB where the column was already
    gone - breaking every eval-store call (list_runs / list_compares /
    store_result / ...) on every MCP restart after the first migration run.
    """
    # Reproduce the post-migration clauses shape: every production column EXCEPT
    # the legacy category / level / province (already dropped by unify-clause-tags).
    empty_db.execute(
        "CREATE TABLE clauses ("
        "  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
        "  contract_type TEXT NOT NULL, "
        "  section TEXT NOT NULL, "
        "  body TEXT NOT NULL, "
        "  slot_instructions JSONB NOT NULL DEFAULT '[]'::jsonb, "
        "  law_refs JSONB NOT NULL DEFAULT '[]'::jsonb, "
        "  source_path TEXT, "
        "  source_doc_title TEXT, "
        "  body_hash TEXT NOT NULL, "
        "  manual BOOLEAN NOT NULL DEFAULT false, "
        "  tags JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "  tag_review JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "  created_at TEXT NOT NULL, "
        "  updated_at TEXT NOT NULL"
        ")"
    )
    empty_db.commit()

    ensure_schema(empty_db)  # must not raise

    cols = {
        r["column_name"]
        for r in empty_db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'clauses'"
        ).fetchall()
    }
    assert "category" not in cols  # legacy column stays dropped
    assert "level" not in cols
    assert "province" not in cols
    assert {"manual", "tags", "tag_review"} <= cols  # additive columns present
