"""Tests for the web human-review task store (change add-web-human-review).

Covers the spec's storage, blind-annotation, slot-independence and
conditional-decision requirements against a live local PostgreSQL (the shared
``seeded_db`` fixture).
"""

from __future__ import annotations

import pytest

from src.eval import review
from src.eval.errors import NotFoundError
from src.eval.store import store_result

RUBRIC = "contract_lease_v3"


def _seed_rubric(conn) -> None:
    """A contract rubric + one criterion so the task join finds guidance."""
    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        "VALUES (%s, 'contract', 'local', NULL, 'lease test', '2026-01-01T00:00:00+00:00')",
        (RUBRIC,),
    )
    conn.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'legal_citation_accuracy', '法条引用准确性', "
        "       'PASS 当且仅当所引法条与条文内容一致', 0 FROM rubrics WHERE name = %s",
        (RUBRIC,),
    )
    conn.commit()


def _make_run(conn, *, rubric: str = RUBRIC, draft: str = "租赁合同草稿正文") -> int:
    """Insert one eval run with two criterion verdicts; returns the run id."""
    return store_result(
        {
            "rubric": rubric,
            "score": 0.0,
            "max_score": 1.0,
            "all_pass": 0,
            "n_criteria": 2,
            "n_passed": 1,
            "judge_model": "test-judge",
            "criteria_results": [
                {"id": "legal_citation_accuracy", "title": "法条引用准确性",
                 "verdict": "fail", "reasoning": "引用了已废止的合同法"},
                {"id": "parties", "title": "当事人条款",
                 "verdict": "pass", "reasoning": "当事人信息完整"},
            ],
        },
        db_path=conn,
        draft_text=draft,
    )


def _result_ids(conn, run_id: int) -> list[int]:
    cur = conn.execute(
        "SELECT id FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal",
        (run_id,),
    )
    return [r["id"] for r in cur.fetchall()]


# --- storage --------------------------------------------------------------- #


def test_create_batch_is_idempotent(seeded_db):
    _seed_rubric(seeded_db)
    run_id = _make_run(seeded_db)
    ids = _result_ids(seeded_db, run_id)

    first = review.create_batch(
        batch_id="b1", batch_type="validity", eval_criteria_result_ids=ids, db=seeded_db
    )
    assert first["created"] == 2 and first["total"] == 2

    second = review.create_batch(
        batch_id="b1", batch_type="validity", eval_criteria_result_ids=ids, db=seeded_db
    )
    assert second["created"] == 0 and second["existing"] == 2 and second["total"] == 2


def test_create_batch_creates_one_slot_per_annotator(seeded_db):
    _seed_rubric(seeded_db)
    ids = _result_ids(seeded_db, _make_run(seeded_db))

    out = review.create_batch(
        batch_id="b2", batch_type="validity", eval_criteria_result_ids=ids,
        annotators=2, db=seeded_db,
    )
    assert out["created"] == 4  # 2 results x 2 slots


def test_create_batch_rejects_bad_input(seeded_db):
    with pytest.raises(ValueError):
        review.create_batch(batch_id="x", batch_type="nope", eval_criteria_result_ids=[1], db=seeded_db)
    with pytest.raises(ValueError):
        review.create_batch(batch_id="x", batch_type="validity", eval_criteria_result_ids=[], db=seeded_db)
    with pytest.raises(ValueError):
        review.create_batch(batch_id="x", batch_type="validity", eval_criteria_result_ids=[1], annotators=0, db=seeded_db)


def test_cascade_delete_removes_tasks(seeded_db):
    _seed_rubric(seeded_db)
    run_id = _make_run(seeded_db)
    ids = _result_ids(seeded_db, run_id)
    review.create_batch(batch_id="b3", batch_type="validity", eval_criteria_result_ids=ids, db=seeded_db)

    seeded_db.execute("DELETE FROM eval_runs WHERE id = %s", (run_id,))
    seeded_db.commit()
    cur = seeded_db.execute("SELECT count(*) AS n FROM review_tasks WHERE batch_id = 'b3'")
    assert cur.fetchone()["n"] == 0


def test_contract_type_from_rubric():
    assert review.contract_type_from_rubric("contract_lease_v3") == "lease"
    assert review.contract_type_from_rubric("contract_real_estate_lease_v2") == "real_estate_lease"
    assert review.contract_type_from_rubric("h_rubric") is None
    assert review.contract_type_from_rubric(None) is None


# --- blind vs verification forms ------------------------------------------- #


def test_validity_detail_is_blind_while_pending(seeded_db):
    _seed_rubric(seeded_db)
    ids = _result_ids(seeded_db, _make_run(seeded_db))
    review.create_batch(batch_id="b4", batch_type="validity", eval_criteria_result_ids=ids, db=seeded_db)

    task = review.list_tasks(batch_id="b4", db=seeded_db)[0]
    detail = review.get_task_detail(task["id"], db=seeded_db)

    assert detail["blind"] is True
    assert detail["model_verdict"] is None and detail["model_reasoning"] is None
    assert detail["criterion_guidance"] == "PASS 当且仅当所引法条与条文内容一致"
    assert detail["draft_text"] == "租赁合同草稿正文"
    assert detail["contract_type"] == "lease"
    assert detail["allowed_verdicts"] == ["pass", "fail"]


def test_validity_detail_reveals_model_after_decision(seeded_db):
    _seed_rubric(seeded_db)
    ids = _result_ids(seeded_db, _make_run(seeded_db))
    review.create_batch(batch_id="b5", batch_type="validity", eval_criteria_result_ids=ids, db=seeded_db)
    task = review.list_tasks(batch_id="b5", db=seeded_db)[0]

    review.decide_task(task_id=task["id"], annotator="alice", verdict="fail", db=seeded_db)
    detail = review.get_task_detail(task["id"], db=seeded_db)

    assert detail["blind"] is False
    assert detail["model_verdict"] in ("pass", "fail")
    assert detail["annotator"] == "alice" and detail["annotator_verdict"] == "fail"


def test_gold_curation_detail_shows_model_verdict_while_pending(seeded_db):
    _seed_rubric(seeded_db)
    ids = _result_ids(seeded_db, _make_run(seeded_db))
    review.create_batch(batch_id="b6", batch_type="gold_curation", eval_criteria_result_ids=ids, db=seeded_db)

    task = review.list_tasks(batch_id="b6", db=seeded_db)[0]
    detail = review.get_task_detail(task["id"], db=seeded_db)

    assert detail["blind"] is False
    assert detail["model_verdict"] in ("pass", "fail")
    assert detail["model_reasoning"]
    assert detail["allowed_verdicts"] == ["approved", "rejected", "skipped"]


def test_get_task_detail_missing_raises(seeded_db):
    with pytest.raises(NotFoundError):
        review.get_task_detail(999999, db=seeded_db)


# --- decisions ------------------------------------------------------------- #


def test_decide_is_conditional_and_second_annotator_loses(seeded_db):
    _seed_rubric(seeded_db)
    ids = _result_ids(seeded_db, _make_run(seeded_db))
    review.create_batch(batch_id="b7", batch_type="validity", eval_criteria_result_ids=ids, db=seeded_db)
    task = review.list_tasks(batch_id="b7", db=seeded_db)[0]

    first = review.decide_task(task_id=task["id"], annotator="alice", verdict="fail", db=seeded_db)
    assert first["ok"] is True

    second = review.decide_task(task_id=task["id"], annotator="bob", verdict="pass", db=seeded_db)
    assert second["ok"] is False and second["decided_by"] == "alice"

    detail = review.get_task_detail(task["id"], db=seeded_db)
    assert detail["annotator"] == "alice" and detail["annotator_verdict"] == "fail"


def test_decide_rejects_verdict_not_allowed_for_batch_type(seeded_db):
    _seed_rubric(seeded_db)
    ids = _result_ids(seeded_db, _make_run(seeded_db))
    review.create_batch(batch_id="b8", batch_type="validity", eval_criteria_result_ids=ids, db=seeded_db)
    task = review.list_tasks(batch_id="b8", db=seeded_db)[0]

    with pytest.raises(ValueError):
        review.decide_task(task_id=task["id"], annotator="alice", verdict="approved", db=seeded_db)
    with pytest.raises(ValueError):
        review.decide_task(task_id=task["id"], annotator="", verdict="pass", db=seeded_db)


def test_list_tasks_hides_other_slots_after_same_annotator_decided(seeded_db):
    """One annotator must not be able to claim both slots of the same item."""
    _seed_rubric(seeded_db)
    ids = _result_ids(seeded_db, _make_run(seeded_db))
    review.create_batch(
        batch_id="b9", batch_type="validity", eval_criteria_result_ids=ids,
        annotators=2, db=seeded_db,
    )
    pending = review.list_tasks(batch_id="b9", status="pending", db=seeded_db)
    first_item_slots = [t for t in pending if t["eval_criteria_result_id"] == ids[0]] if "eval_criteria_result_id" in pending[0] else None
    # list_tasks does not project the FK; re-read it from the detail of the first task
    target = review.get_task_detail(pending[0]["id"], db=seeded_db)
    target_result_id = target["eval_criteria_result_id"]

    review.decide_task(task_id=pending[0]["id"], annotator="alice", verdict="fail", db=seeded_db)

    alice_queue = review.list_tasks(batch_id="b9", status="pending", for_annotator="alice", db=seeded_db)
    for t in alice_queue:
        assert review.get_task_detail(t["id"], db=seeded_db)["eval_criteria_result_id"] != target_result_id

    bob_queue = review.list_tasks(batch_id="b9", status="pending", for_annotator="bob", db=seeded_db)
    bob_targets = [
        t for t in bob_queue
        if review.get_task_detail(t["id"], db=seeded_db)["eval_criteria_result_id"] == target_result_id
    ]
    assert bob_targets, "the other annotator must still see the item's remaining slot"


# --- stats ----------------------------------------------------------------- #


def test_list_batches_and_batch_stats(seeded_db):
    _seed_rubric(seeded_db)
    ids = _result_ids(seeded_db, _make_run(seeded_db))
    review.create_batch(batch_id="b10", batch_type="validity", eval_criteria_result_ids=ids, db=seeded_db)
    tasks = review.list_tasks(batch_id="b10", db=seeded_db)
    review.decide_task(task_id=tasks[0]["id"], annotator="alice", verdict="fail", db=seeded_db)

    batches = review.list_batches(db=seeded_db)
    row = next(b for b in batches if b["batch_id"] == "b10")
    assert row["batch_type"] == "validity"
    assert row["total"] == 2 and row["decided"] == 1 and row["pending"] == 1
    assert row["annotators"] == 1

    stats = review.batch_stats("b10", db=seeded_db)
    assert stats["by_annotator"] == [{"annotator": "alice", "decided": 1, "positive": 0}]
