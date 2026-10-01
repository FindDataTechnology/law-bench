"""Tests for the web-review export/QC script (change add-web-human-review).

Unit tests run on synthetic rows (no DB); one end-to-end test drives the real
``review_tasks`` rows through load -> report -> export.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts" / "finetune"))

import web_review_export as xp  # noqa: E402

from src.eval import review  # noqa: E402
from src.eval.store import store_result  # noqa: E402

RUBRIC = "contract_lease_v3"


def _row(**kw) -> dict:
    base = {
        "task_id": 1, "batch_id": "b", "batch_type": "validity", "slot": 1,
        "annotator": "alice", "annotator_verdict": "pass", "note": None,
        "reviewed_at": "2026-09-21T00:00:00+00:00",
        "result_id": 10, "criterion_id": "c1", "criterion_title": "t",
        "model_verdict": "pass", "model_reasoning": "r",
        "run_id": 5, "rubric_name": RUBRIC, "draft_text": "草稿", "judge_model": "j",
        "scored_at": "2026-09-20T00:00:00+00:00",
    }
    base.update(kw)
    return base


# --- label normalization --------------------------------------------------- #


def test_normalized_label_maps_both_batch_types():
    assert xp._normalized_label(_row(annotator_verdict="fail")) == "fail"
    assert xp._normalized_label(
        _row(batch_type="gold_curation", annotator_verdict="approved")) == "pass"
    assert xp._normalized_label(
        _row(batch_type="gold_curation", annotator_verdict="rejected")) == "fail"
    assert xp._normalized_label(
        _row(batch_type="gold_curation", annotator_verdict="skipped")) is None


def test_agrees_uses_the_judge_axis():
    assert xp._agrees(_row(annotator_verdict="pass", model_verdict="pass")) is True
    assert xp._agrees(_row(annotator_verdict="fail", model_verdict="pass")) is False
    assert xp._agrees(_row(batch_type="gold_curation", annotator_verdict="approved",
                           model_verdict="fail")) is False
    assert xp._agrees(_row(batch_type="gold_curation", annotator_verdict="skipped")) is None
    assert xp._agrees(_row(model_verdict="unknown")) is None


# --- kappa ----------------------------------------------------------------- #


def test_kappa_perfect_agreement():
    pairs = [("pass", "pass")] * 5 + [("fail", "fail")] * 5
    assert xp.cohens_kappa(pairs) == pytest.approx(1.0)


def test_kappa_known_value():
    # po = 0.8; both marginals 0.9 -> pe = 0.82 -> kappa = -0.02/0.18 (worse than
    # chance given the marginals, which is what a near-constant rater pair scores)
    pairs = [("pass", "pass")] * 8 + [("pass", "fail"), ("fail", "pass")]
    assert xp.cohens_kappa(pairs) == pytest.approx(-0.1111, abs=1e-4)


def test_kappa_undefined_cases():
    assert xp.cohens_kappa([]) is None
    assert xp.cohens_kappa([("pass", "pass")] * 4) is None  # degenerate marginals


# --- report ---------------------------------------------------------------- #


def test_report_flags_perfect_judge_agreement(capsys):
    rows = [_row(task_id=i, result_id=i, annotator="bot", annotator_verdict="pass",
                 model_verdict="pass") for i in range(6)]
    out = xp._report(rows, warn_threshold=0.98)
    assert out["flagged"] and out["flagged"][0][0] == "bot"
    assert "疑似机器代打" in capsys.readouterr().out


def test_report_does_not_flag_a_dissenting_human(capsys):
    rows = [_row(task_id=i, result_id=i, annotator="human",
                 annotator_verdict=("fail" if i % 2 else "pass"),
                 model_verdict="pass") for i in range(6)]
    out = xp._report(rows, warn_threshold=0.98)
    assert out["flagged"] == []
    assert "human-vs-judge agreement overall: 0.500" in capsys.readouterr().out


def test_report_computes_pairwise_kappa(capsys):
    rows = []
    for i in range(4):
        rows.append(_row(task_id=i * 2, result_id=i, slot=1, annotator="a",
                         annotator_verdict="pass", model_verdict="pass"))
        rows.append(_row(task_id=i * 2 + 1, result_id=i, slot=2, annotator="b",
                         annotator_verdict=("fail" if i == 3 else "pass"),
                         model_verdict="pass"))
    out = xp._report(rows, warn_threshold=0.98)
    text = capsys.readouterr().out
    assert out["pairs"] == 4
    assert "Cohen's kappa" in text


# --- export ---------------------------------------------------------------- #


def test_export_routes_approved_rows_without_a_legal_basis_to_the_worklist(tmp_path):
    """Today's data has no law reference: nothing is promotable, nothing invented."""
    rows = [
        _row(task_id=1, result_id=11, batch_type="gold_curation", annotator_verdict="approved"),
        _row(task_id=2, result_id=12, batch_type="gold_curation", annotator_verdict="rejected"),
        _row(task_id=3, result_id=13, batch_type="validity", annotator_verdict="pass"),
    ]
    out_path = tmp_path / "gold.jsonl"
    xp._export(rows, out_path)

    # the gold file is NOT written: an empty one would falsely unblock the flywheel
    assert not out_path.exists()
    worklist = tmp_path / "gold.jsonl.incomplete.jsonl"
    records = [json.loads(line) for line in worklist.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1  # rejected + validity rows are not exported at all
    rec = records[0]
    assert rec["verdict"] == "pass" and rec["tier"] == "gold"
    assert rec["clause_text"] == {"body": "草稿"}
    assert rec["legal_base"] == {"source": "", "text": ""}
    assert rec["provenance"]["reviewer"] == "human"
    assert rec["provenance"]["annotated_by"] == "alice"
    assert rec["provenance"]["source"].startswith(
        "review_tasks:1|eval_criteria_results:11|eval_runs:5")
    assert "legal_base" in rec["_validation_error"]


def test_exported_gold_passes_the_downstream_validator(tmp_path):
    """A row carrying a legal basis exports as gold the promote/gate flow accepts."""
    from export_dataset import validate_quadruple

    rows = [_row(task_id=1, result_id=11, batch_type="gold_curation",
                 annotator_verdict="approved", model_verdict="fail",
                 legal_base_source="中华人民共和国民法典",
                 legal_base_text="第七百零三条", citation="民法典第七百零三条")]
    out_path = tmp_path / "gold.jsonl"
    xp._export(rows, out_path)

    records = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    validate_quadruple(records[0], 0)  # raises if the shape or rules are wrong
    assert not (tmp_path / "gold.jsonl.incomplete.jsonl").exists()


# --- end to end ------------------------------------------------------------ #


def test_end_to_end_load_report_export(seeded_db, tmp_path, capsys):
    seeded_db.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        "VALUES (%s, 'contract', 'local', NULL, 't', '2026-01-01T00:00:00+00:00')", (RUBRIC,))
    seeded_db.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'c1', 'd', 'g', 0 FROM rubrics WHERE name = %s", (RUBRIC,))
    seeded_db.commit()
    run_id = store_result(
        {"rubric": RUBRIC, "score": 0.0, "max_score": 1.0, "all_pass": 0,
         "n_criteria": 1, "n_passed": 0, "judge_model": "test-judge",
         "criteria_results": [{"id": "c1", "title": "t", "verdict": "fail",
                               "reasoning": "模型理由"}]},
        db_path=seeded_db, draft_text="合同草稿",
    )
    cur = seeded_db.execute(
        "SELECT id FROM eval_criteria_results WHERE run_id = %s", (run_id,))
    result_id = cur.fetchone()["id"]

    review.create_batch(batch_id="e2e", batch_type="gold_curation",
                        eval_criteria_result_ids=[result_id], annotators=2, db=seeded_db)
    tasks = review.list_tasks(batch_id="e2e", status="pending", db=seeded_db)
    review.decide_task(task_id=tasks[0]["id"], annotator="alice", verdict="approved",
                       note="核对过法条", db=seeded_db)
    review.decide_task(task_id=tasks[1]["id"], annotator="bob", verdict="approved", db=seeded_db)

    import src.eval.db as dbmod
    rows = xp._load("e2e")
    assert len(rows) == 2
    stats = xp._report(rows, warn_threshold=0.98)
    # both annotators endorsed the model's fail verdict -> both at 100% judge agreement
    assert {who for who, _ in stats["flagged"]} == {"alice", "bob"} or stats["flagged"] == []

    out_path = tmp_path / "e2e_gold.jsonl"
    xp._export(rows, out_path)
    worklist = tmp_path / "e2e_gold.jsonl.incomplete.jsonl"
    records = [json.loads(l) for l in worklist.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert all(r["provenance"]["reviewer"] == "human" for r in records)
    assert {r["provenance"]["annotated_by"] for r in records} == {"alice", "bob"}
    assert all("review_tasks:" in r["provenance"]["source"] for r in records)
    # both endorsed a fail verdict, but the eval-side data carries no law
    # reference, so neither is promotable yet
    assert not out_path.exists()
