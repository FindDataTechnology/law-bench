"""Ledger integration tests: real writers, real DB, fake judge (no LLM).

These are the tests that would have caught the failure mode the whole change
exists to prevent — a run that records a score but cannot say what it scored,
with what ruler, or whether the result is even comparable to the last one.

Everything here goes through the REAL write paths (``evaluate_contract`` →
``store_result``, ``run_calibration`` → ``store_result``) against the throwaway
Postgres DB from ``conftest``. Only the judge is faked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _fakes import FakeJudge
from src.bench import verdicts
from src.bench.calibration import run_calibration
from src.eval.scoring import evaluate_contract
from src.eval.store import get_run, list_verdicts

_RUBRIC = "l_rubric"  # seeded with criteria c1, c2


def _eval(seeded_db: Path, verdicts_: list, text: str = "合同正文") -> dict:
    return evaluate_contract(
        text, _RUBRIC, judge=FakeJudge(verdicts=verdicts_), max_workers=1,
        db_path=seeded_db,
    )


# --- 3.1 contract channel --------------------------------------------------


def test_result_carries_ledger_identity(seeded_db: Path):
    res = _eval(seeded_db, [True, True])
    subject, ruler = res["verdict_subject"], res["verdict_ruler"]
    assert subject["subject_kind"] == "contract"
    assert subject["subject_version"].startswith("sha256:")
    assert ruler["kind"] == "rubric" and ruler["key"] == _RUBRIC
    assert len(ruler["digest"]) == 64  # sha256 hex
    assert res["verdict_outcome"] == "pass"


def test_ruler_digest_matches_the_shared_kernel(seeded_db: Path):
    """The digest must come from the ONE canonical implementation, not a copy."""
    res = _eval(seeded_db, [True, True])
    from src.bench.verdicts import rubric_ruler

    assert res["verdict_ruler"] == rubric_ruler(_RUBRIC, db_path=seeded_db)


def test_editing_one_criterion_moves_the_ruler_digest(seeded_db: Path):
    before = _eval(seeded_db, [True, True])["verdict_ruler"]["digest"]
    seeded_db.execute(
        "UPDATE criteria SET guidance = guidance || ' [edited]' "
        "WHERE name = 'c1'"
    )
    after = _eval(seeded_db, [True, True])["verdict_ruler"]["digest"]
    assert before != after, "a changed ruler must not keep its old digest"


def test_same_text_same_subject_edited_text_new_subject(seeded_db: Path):
    a = _eval(seeded_db, [True, True], text="同一份合同")
    b = _eval(seeded_db, [True, True], text="同一份合同")
    c = _eval(seeded_db, [True, True], text="同一份合同（改过）")
    assert a["verdict_subject"] == b["verdict_subject"]
    assert c["verdict_subject"]["subject_version"] != a["verdict_subject"]["subject_version"]


def test_stored_row_round_trips_the_ledger_columns(seeded_db: Path):
    res = _eval(seeded_db, [False, False])
    from src.eval.store import store_result
    from src.bench.verdicts import provisional

    subject, ruler = res["verdict_subject"], res["verdict_ruler"]
    run_id = store_result(
        res, db_path=seeded_db,
        subject_kind=subject["subject_kind"], subject_key=subject["subject_key"],
        subject_version=subject["subject_version"],
        ruler_kind=ruler["kind"], ruler_key=ruler["key"], ruler_digest=ruler["digest"],
        gate="all-pass", outcome=res["verdict_outcome"],
        provisional=provisional(res["judge_model"], None),
    )
    row = get_run(run_id, db_path=seeded_db)
    assert row["subject_kind"] == "contract"
    assert row["subject_version"] == subject["subject_version"]
    assert row["ruler_digest"] == ruler["digest"]
    assert row["gate"] == "all-pass"
    assert row["outcome"] == "fail"


def test_outcome_derives_from_all_pass_when_not_given(seeded_db: Path):
    """A legacy writer gets an honest outcome without passing one."""
    from src.eval.store import store_result

    res = _eval(seeded_db, [True, True])
    passed = store_result(res, db_path=seeded_db)
    failed = store_result(_eval(seeded_db, [False, True]), db_path=seeded_db)
    assert get_run(passed, db_path=seeded_db)["outcome"] == "pass"
    assert get_run(failed, db_path=seeded_db)["outcome"] == "fail"


def test_all_invalid_is_inconclusive_not_fail():
    """Every criterion invalid = nothing was judged. Blaming the contract for a
    broken judge is exactly the false negative this vocabulary exists to stop."""
    assert verdicts.score_outcome(False, n_total=0, n_invalid=2) == "inconclusive"
    assert verdicts.score_outcome(False, n_total=1, n_invalid=1) == "fail"
    assert verdicts.score_outcome(True, n_total=2, n_invalid=0) == "pass"


# --- 3.3 calibration channel ----------------------------------------------


def _gold(n: int, agree: bool) -> list[dict]:
    return [
        {"judge_verdict": agree, "human_verdict": True, "confidence": 0.9,
         "confidence_source": "vote_share"}
        for _ in range(n)
    ]


def _gold_mixed(n: int) -> list[dict]:
    """A judge that agrees with a human on BOTH classes (gates can pass).

    All-one-class gold makes balanced accuracy undefinable, which is a different
    (also correct) failure — not what these tests are about.
    """
    return [
        {"judge_verdict": i % 2 == 0, "human_verdict": i % 2 == 0,
         "confidence": 0.9, "confidence_source": "vote_share"}
        for i in range(n)
    ]


def test_calibration_lands_a_calibrated_gate_verdict(seeded_db: Path):
    res = run_calibration(
        None, judge_model="glm-5.2", prompt_version="v2",
        gold_records=_gold_mixed(60), db_path=seeded_db,
    )
    row = get_run(res["run_id"], db_path=seeded_db)
    assert row["gate"] == "calibrated"
    assert row["subject_kind"] == "judge"
    assert row["subject_key"] == "glm-5.2@v2"
    assert row["ruler_kind"] == "gold-set"
    assert len(row["ruler_digest"]) == 64


def test_calibration_outcome_is_three_state(seeded_db: Path):
    """Gates passing on too little evidence is 'inconclusive', not 'pass'."""
    tiny = run_calibration(
        None, judge_model="glm-5.2", prompt_version="v2",
        gold_records=_gold_mixed(5), db_path=seeded_db,
    )
    assert tiny["all_pass"] is True  # the legacy gate did pass...
    assert get_run(tiny["run_id"], db_path=seeded_db)["outcome"] == "inconclusive"

    big = run_calibration(
        None, judge_model="glm-5.2", prompt_version="v2",
        gold_records=_gold_mixed(60), db_path=seeded_db,
    )
    assert get_run(big["run_id"], db_path=seeded_db)["outcome"] == "pass"


def _gold_disagree(n: int) -> list[dict]:
    """A judge that gets every human label backwards (both classes present)."""
    return [
        {"judge_verdict": i % 2 != 0, "human_verdict": i % 2 == 0,
         "confidence": 0.9, "confidence_source": "vote_share"}
        for i in range(n)
    ]


def test_all_disagreement_fails_the_gate(seeded_db: Path):
    res = run_calibration(
        None, judge_model="glm-5.2", prompt_version="v2",
        gold_records=_gold_disagree(60), db_path=seeded_db,
    )
    assert get_run(res["run_id"], db_path=seeded_db)["outcome"] == "fail"


def test_changing_gold_set_moves_the_ruler_digest(seeded_db: Path):
    a = run_calibration(None, judge_model="glm-5.2", prompt_version="v2",
                        gold_records=_gold_mixed(60), db_path=seeded_db)
    b = run_calibration(None, judge_model="glm-5.2", prompt_version="v2",
                        gold_records=_gold_mixed(61), db_path=seeded_db)
    assert (get_run(a["run_id"], db_path=seeded_db)["ruler_digest"]
            != get_run(b["run_id"], db_path=seeded_db)["ruler_digest"])


def test_provisional_reads_the_ledger(seeded_db: Path):
    """Derived, not configured: no calibration → provisional; a passing one → not."""
    assert verdicts.provisional("glm-5.2", "v2", db_path=seeded_db) is True

    run_calibration(None, judge_model="glm-5.2", prompt_version="v2",
                    gold_records=_gold_mixed(60), db_path=seeded_db)
    assert verdicts.provisional("glm-5.2", "v2", db_path=seeded_db) is False


def test_inconclusive_calibration_leaves_the_judge_provisional(seeded_db: Path):
    run_calibration(None, judge_model="glm-5.2", prompt_version="v2",
                    gold_records=_gold_mixed(5), db_path=seeded_db)
    assert verdicts.provisional("glm-5.2", "v2", db_path=seeded_db) is True


# --- cross-line comparability (task 6.2) -----------------------------------


def test_two_lines_land_in_one_queryable_set(seeded_db: Path):
    """The whole point: a contract verdict and a calibration verdict are the
    same shape, so one query can read across product lines."""
    _eval(seeded_db, [True, True])
    run_calibration(None, judge_model="glm-5.2", prompt_version="v2",
                    gold_records=_gold(60, agree=True), db_path=seeded_db)
    from src.eval.store import store_result

    res = _eval(seeded_db, [True, True])
    s, r = res["verdict_subject"], res["verdict_ruler"]
    store_result(res, db_path=seeded_db,
                 subject_kind=s["subject_kind"], subject_key=s["subject_key"],
                 subject_version=s["subject_version"],
                 ruler_kind=r["kind"], ruler_key=r["key"], ruler_digest=r["digest"],
                 gate="all-pass", outcome=res["verdict_outcome"])

    rows = list_verdicts(limit=100, db_path=seeded_db)
    gates = {r["gate"] for r in rows if r["gate"]}
    assert {"all-pass", "calibrated"} <= gates
    # every ledger row carries the same shape of identity, whichever line wrote it
    for r in rows:
        if r["gate"]:
            assert r["subject_kind"] and r["subject_version"] and r["ruler_digest"]


# --- 3.4 one question, one answer -----------------------------------------


@pytest.mark.parametrize(
    "records",
    [
        None,                              # no calibration at all
        _gold_mixed(5),                    # gates pass, too little evidence
        _gold_mixed(60),                   # gates pass, enough evidence
        _gold_disagree(60),                # gates fail
    ],
    ids=["no-record", "too-little", "passing", "failing"],
)
def test_pack_gate_and_provisional_agree(seeded_db: Path, records):
    """Two read paths answer "is this judge calibrated?" — they must not differ.

    ``calibration.is_calibrated`` (the pack's gold_judge gate) and
    ``verdicts.provisional`` (the ledger's trust flag) used to be independent
    judgments. If they can disagree, a pack can be told its judge is fine while
    every verdict it produces is stamped provisional.
    """
    from src.bench.calibration import is_calibrated

    if records is not None:
        run_calibration(None, judge_model="glm-5.2", prompt_version="v2",
                        gold_records=records, db_path=seeded_db)

    gate_ok, _reason = is_calibrated(
        seeded_db, judge_model="glm-5.2", prompt_version="v2",
        db_path=seeded_db,
    )
    is_provisional = verdicts.provisional("glm-5.2", "v2", db_path=seeded_db)
    assert gate_ok == (not is_provisional)
