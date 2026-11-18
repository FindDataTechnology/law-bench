"""Fail-loud structural-soundness tests for the judge scoring chain.

Covers change ``add-judge-misread-remediation``:

- ``classify_structural_soundness`` (pure): marker_in_contract positives
  (zh + en high-confidence patterns), near-miss negatives (marker mentioned
  as the judge's OWN output label, negated demands, contract-content
  requirements), contract_violation on success + empty/unsigned reasoning,
  and the pre-existing error channel (error set -> classifier stays out).
- ``evaluate_contract`` integration: invalid rows carry verdict="invalid" +
  ``invalid_reason``, are excluded from the n_criteria denominator and
  n_passed, and surface in the additive ``n_invalid`` / ``invalid_rate`` keys
  (宁无效不假绿: an all-invalid run never reads as ALL PASS).
- ``build_judge_criteria`` prompt-domain fallback: domain row wins when
  present; a missing/unreachable domain falls back to the module constant,
  byte-identical, so the scoring chain never breaks on a prompt-domain
  failure (design D2).

Hermetic: no network; the judge path is stubbed with scripted metric doubles
(same contract as tests/_fakes.py), the DB is the throwaway session DB.
"""

from __future__ import annotations

import json

import pytest

import src.eval.scoring as scoring
from _fakes import FakeJudge
from src.eval.scoring import (
    EVAL_PROMPT_VERSION,
    JUDGE_SCORING_PROMPT_NAME,
    JUDGE_SCORING_PROMPT_PROVENANCE,
    JUDGE_SCORING_PROMPT_PURPOSE,
    _JUDGE_STRUCTURE_RULES,
    build_judge_criteria,
    classify_structural_soundness,
    ensure_judge_scoring_prompt,
    evaluate_contract,
)

_RUBRIC = "l_rubric"  # seeded with criteria c1, c2 by the shared fixture


# --- classify_structural_soundness (pure) -------------------------------------


class TestMarkerInContract:
    @pytest.mark.parametrize(
        "reasoning",
        [
            # zh: attributes the marker requirement to the contract / doc text
            "该合同应当包含PASS标记，表明各条款均已通过。",
            "文档需要添加FAIL标记以示未通过项。",
            "合同正文中应包含PASS标记。",
            # en: modal + verb + marker chained to the subject
            "The contract should include PASS/FAIL markers in its text.",
            "The document must contain a FAIL marker for the missing clause.",
            "document needs to add PASS labels to each section",
        ],
    )
    def test_positives_flagged(self, reasoning):
        assert classify_structural_soundness(reasoning, True, None) == "marker_in_contract"

    @pytest.mark.parametrize(
        "reasoning",
        [
            # negated demands: the judge correctly APPLYING rule 1
            "合同中不应包含PASS标记——评分标记属于判官输出，不属于合同内容。\nCONFIDENCE: 0.90",
            "文档无需添加PASS标记。\nCONFIDENCE: 0.90",
            "The contract must not include PASS markers; verdict labels are "
            "the judge's own output.\nCONFIDENCE: 0.90",
            # PASS/FAIL mentioned as the judge's own output label
            "The criterion fails. PASS/FAIL markers are the judge's output, "
            "never part of the evaluated document.\nCONFIDENCE: 0.90",
            "判官应输出明确的PASS/FAIL判定，而不是在合同里找标记。\nCONFIDENCE: 0.90",
            # contract-content requirements without any marker attribution
            "合同第五条约定了价款，但缺少验收条款，因此判FAIL。\nCONFIDENCE: 0.90",
            "The document should specify a delivery deadline; it does not.\nCONFIDENCE: 0.90",
            # field misreading discussion (no marker attribution)
            "该标题行不是字段值，判定依据是正文内容。\nCONFIDENCE: 0.90",
        ],
    )
    def test_near_miss_negatives_not_flagged(self, reasoning):
        assert classify_structural_soundness(reasoning, True, None) is None

    def test_marker_detected_even_on_fail_verdict(self):
        # the misread is about the REASONING, not the verdict polarity
        assert classify_structural_soundness(
            "该合同应当包含PASS标记。", False, None
        ) == "marker_in_contract"


class TestContractViolation:
    def test_success_with_empty_reasoning(self):
        assert classify_structural_soundness(None, True, None) == "contract_violation"
        assert classify_structural_soundness("", True, None) == "contract_violation"
        assert classify_structural_soundness("   \n  ", True, None) == "contract_violation"

    def test_success_without_confidence_tail(self):
        assert (
            classify_structural_soundness("The clause is present.", True, None)
            == "contract_violation"
        )
        assert (
            classify_structural_soundness("done\nCONFIDENCE: high", True, None)
            == "contract_violation"
        )
        # mid-text marker is malformed (parse_confidence returns None)
        assert (
            classify_structural_soundness("CONFIDENCE: 0.5 was my guess", True, None)
            == "contract_violation"
        )

    def test_success_with_wellformed_tail_is_sound(self):
        assert classify_structural_soundness("ok\nCONFIDENCE: 0.90", True, None) is None

    def test_fail_verdict_without_tail_is_not_contract_violation(self):
        # the confidence screen applies to pass verdicts only (existing
        # fail behavior unchanged)
        assert classify_structural_soundness("no tail here", False, None) is None


class TestErrorChannel:
    def test_error_set_is_invalid_regardless_of_other_fields(self):
        """judge 调用失败 → 一律 `invalid`，**不再**返回 None。

        **这条契约在 2026-11-09 变了**（审计 03 §4，提交见 `harden-ponytail-p0`
        `03 §4` 条目）。旧契约是「error 归既有错误通道管，本分类器返回 None」，
        后果是：measure 从未完成 → `success=False` → `verdict="fail"` **并计入分母**。
        中继饱和时一批 `APITimeoutError` 就把合格条款判成不合格，自迭代循环据此
        重写本来正确的内容——`property_service` 掉到 0/10 就是这条路。

        新契约：没测成 ≠ 不合格。带 error 的行一律 `invalid`，不计分母、不计通过，
        与同文件「宁无效不假绿」的原则一致。

        下面三条覆盖三种「同时还有别的信号」的组合——都必须以 error 为准。
        """
        # 1. error + 看似 pass 的字段
        assert classify_structural_soundness(None, True, "boom") == "judge_call_error"
        # 2. error + 推理文本（文本是旧的/不完整的，不许拿它判结构）
        assert (
            classify_structural_soundness("该合同应当包含PASS标记。", False, "boom")
            == "judge_call_error"
        )
        # 3. error + 完整合法的 pass 文本（仍然 invalid：那次判定根本没过）
        assert (
            classify_structural_soundness("ok\nCONFIDENCE: 0.90", True, "err")
            == "judge_call_error"
        )


# --- evaluate_contract integration --------------------------------------------


class _ScriptedMetric:
    """Metric double honoring the contract scoring reads (see tests/_fakes.py)."""

    def __init__(self, name, *, success, reason, error=None):
        self.name = name
        self.success = success
        self.reason = reason
        self.error = error
        self.evaluation_model = "fake-judge"

    def measure(self, test_case, _show_indicator=False):
        # quiet no-op: the outcome is pre-scripted on the instance; raising
        # here would be swallowed by _score_one's error guard and flip the row
        # onto the error channel (which the classifier deliberately ignores)
        return None


def _add_two_criteria(conn) -> None:
    """Grow l_rubric to four criteria so four scripted metrics zip 1:1."""
    conn.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'c3', 'd', 'g', 2 FROM rubrics WHERE name = 'l_rubric'"
    )
    conn.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'c4', 'd', 'g', 3 FROM rubrics WHERE name = 'l_rubric'"
    )
    conn.commit()


def _run_scripted(seeded_db, metrics, monkeypatch) -> dict:
    _add_two_criteria(seeded_db)
    monkeypatch.setattr(scoring, "_build_metrics", lambda *a, **k: list(metrics))
    return evaluate_contract(
        "合同正文", _RUBRIC, judge=object(), max_workers=1, db_path=seeded_db
    )


def test_invalid_rows_excluded_from_denominator(seeded_db, monkeypatch):
    metrics = [
        _ScriptedMetric("c1", success=True, reason="clean\nCONFIDENCE: 0.90"),
        _ScriptedMetric("c2", success=False, reason="missing clause\nCONFIDENCE: 0.80"),
        _ScriptedMetric("c3", success=True,
                        reason="该合同应当包含PASS标记。\nCONFIDENCE: 0.95"),
        _ScriptedMetric("c4", success=True, reason=""),
    ]
    res = _run_scripted(seeded_db, metrics, monkeypatch)

    verdicts = [(r["id"], r["verdict"]) for r in res["criteria_results"]]
    assert verdicts == [("c1", "pass"), ("c2", "fail"),
                        ("c3", "invalid"), ("c4", "invalid")]

    by_id = {r["id"]: r for r in res["criteria_results"]}
    assert by_id["c3"]["invalid_reason"] == "marker_in_contract"
    assert by_id["c4"]["invalid_reason"] == "contract_violation"
    # valid rows carry NO invalid_reason key (row shape stays compatible)
    assert "invalid_reason" not in by_id["c1"]
    assert "invalid_reason" not in by_id["c2"]

    # invalid rows are OUT of the denominator, never counted as failed
    assert res["n_criteria"] == 2
    assert res["n_passed"] == 1
    assert res["all_pass"] is False
    assert res["score"] == 0.0
    # additive reporting keys
    assert res["n_invalid"] == 2
    assert res["invalid_rate"] == 0.5
    assert "2 invalid" in res["summary"]


def test_all_invalid_run_never_reads_all_pass(seeded_db, monkeypatch):
    metrics = [
        _ScriptedMetric("c1", success=True, reason="合同应当包含PASS标记。"),
        _ScriptedMetric("c2", success=True, reason=None),
    ]
    res = _run_scripted(seeded_db, metrics, monkeypatch)

    assert all(r["verdict"] == "invalid" for r in res["criteria_results"])
    assert res["n_criteria"] == 0  # denominator empty
    assert res["n_passed"] == 0
    assert res["all_pass"] is False  # 宁无效不假绿
    assert res["score"] == 0.0
    assert res["n_invalid"] == 2
    assert res["invalid_rate"] == 1.0


def test_clean_run_has_zero_invalid_rate(seeded_db, monkeypatch):
    metrics = [
        _ScriptedMetric("c1", success=True, reason="ok\nCONFIDENCE: 0.90"),
        _ScriptedMetric("c2", success=False, reason="bad\nCONFIDENCE: 0.70"),
    ]
    res = _run_scripted(seeded_db, metrics, monkeypatch)
    assert res["n_invalid"] == 0
    assert res["invalid_rate"] == 0.0
    assert res["n_criteria"] == 2
    assert res["n_passed"] == 1
    assert "invalid" not in res["summary"]


# --- prompt-domain fallback (design D2) ----------------------------------------


def test_domain_row_wins_over_constant(seeded_db):
    seeded_db.execute(
        "INSERT INTO prompts (name, contract_type, purpose, content, source, "
        "prompt_type, description, created_at) "
        "VALUES ('judge_scoring_domain_test', 'any', 'judge_scoring', "
        "'DOMAIN RULES TEXT', 'local', 'v2-structure', NULL, "
        "'2026-01-02T00:00:00+00:00')"
    )
    seeded_db.commit()
    text = build_judge_criteria("base criteria", db_path=seeded_db)
    assert text == "base criteria\n\nDOMAIN RULES TEXT"


def test_seeded_prompt_content_is_the_module_constant(seeded_db):
    ensure_judge_scoring_prompt(db_path=seeded_db)
    text = build_judge_criteria("base criteria", db_path=seeded_db)
    # content seeded verbatim from _JUDGE_STRUCTURE_RULES -> byte-identical
    assert text == f"base criteria\n\n{_JUDGE_STRUCTURE_RULES}"


def test_missing_domain_row_falls_back_to_constant(seeded_db):
    # prompts table present but empty -> no row -> module constant
    text = build_judge_criteria("base criteria", db_path=seeded_db)
    assert text == f"base criteria\n\n{_JUDGE_STRUCTURE_RULES}"


def test_unreachable_domain_falls_back_to_constant(seeded_db, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("prompt domain unreachable")

    # the loader imports connect at call time, so patching src.eval.db.connect
    # exercises the real swallow path (any exception -> None -> constant)
    monkeypatch.setattr("src.eval.db.connect", _boom)
    text = build_judge_criteria("base criteria", db_path=seeded_db)
    assert text == f"base criteria\n\n{_JUDGE_STRUCTURE_RULES}"


def test_domain_failure_never_breaks_evaluate_contract(seeded_db, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("prompt domain unreachable")

    monkeypatch.setattr("src.eval.db.connect", _boom)
    res = evaluate_contract(
        "合同正文",
        _RUBRIC,
        judge=FakeJudge(verdicts=[True, True]),
        max_workers=1,
        db_path=seeded_db,
    )
    assert res["all_pass"] is True
    assert res["invalid_rate"] == 0.0


def test_ensure_judge_scoring_prompt_is_idempotent(seeded_db):
    first = ensure_judge_scoring_prompt(db_path=seeded_db)
    seeded_db.execute(
        "UPDATE prompts SET content = 'operator edited' WHERE name = %s",
        (first["name"],),
    )
    seeded_db.commit()
    second = ensure_judge_scoring_prompt(db_path=seeded_db)

    assert second["id"] == first["id"]
    n = seeded_db.execute(
        "SELECT COUNT(*) AS n FROM prompts WHERE purpose = 'judge_scoring'"
    ).fetchone()["n"]
    assert n == 1
    # insert-only seeding: an operator's domain edit is never clobbered
    content = seeded_db.execute(
        "SELECT content FROM prompts WHERE name = %s", (first["name"],)
    ).fetchone()["content"]
    assert content == "operator edited"


def test_ensure_judge_scoring_prompt_row_shape(seeded_db):
    ensure_judge_scoring_prompt(db_path=seeded_db)
    row = seeded_db.execute(
        "SELECT name, contract_type, purpose, content, source, prompt_type, "
        "description FROM prompts WHERE name = %s",
        (JUDGE_SCORING_PROMPT_NAME,),
    ).fetchone()
    assert row["purpose"] == JUDGE_SCORING_PROMPT_PURPOSE == "judge_scoring"
    assert row["prompt_type"] == EVAL_PROMPT_VERSION == "v2-structure"
    assert row["source"] == "local"
    assert row["content"] == _JUDGE_STRUCTURE_RULES
    assert json.loads(row["description"]) == JUDGE_SCORING_PROMPT_PROVENANCE
