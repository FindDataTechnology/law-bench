"""Tests for ``src/eval/compare.py``: orchestration, matrix, and prompt resolution.

Runs fully offline: the drafter is an injected ``draft_fn`` and the judge is the
deterministic ``FakeJudge`` (max_workers=1 so verdicts are consumed in criteria
order). No DRAFTER LLM and no judge endpoint are constructed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.eval.compare import build_matrix, load_prompts, run_compare
from src.eval.errors import ValidationError
from src.eval.manage import create_prompt, create_rubric
from src.eval.store import ensure_schema

from _fakes import FakeJudge


def _seed_area(db: Path) -> None:
    """Create one rubric (2 criteria) + two sale prompts on the throwaway DB."""
    ensure_schema(db)
    create_rubric(
        "contract_sale_v1", "contract", "sale test",
        [
            {"name": "party_id", "description": "party identification",
             "guidance": "PASS if parties named; FAIL otherwise"},
            {"name": "price", "description": "price and payment",
             "guidance": "PASS if price stated; FAIL otherwise"},
        ],
        db_path=db,
    )
    create_prompt("draft_sale", "sale", "drafting", "draft a sale contract", "d",
                  "baseline", db_path=db)
    create_prompt("draft_sale_v2", "sale", "drafting", "draft a better sale contract",
                  "d2", "experimental", db_path=db)


def _draft_fn_tracker():
    calls = {"n": 0}

    def fn(task, content, templates):
        calls["n"] += 1
        return f"DRAFT #{calls['n']}"

    return fn, calls


def test_run_compare_creates_one_compare_owning_n_runs(seeded_db: Path):
    _seed_area(seeded_db)
    draft_fn, calls = _draft_fn_tracker()
    # 2 prompts x 1 draft x 2 criteria = 4 verdicts
    judge = FakeJudge(verdicts=[True, False, False, True], model_name="fake-judge")
    prompts = load_prompts(["draft_sale", "draft_sale_v2"], db_path=seeded_db)

    comp = run_compare(
        "sale", "contract_sale_v1", "task", prompts,
        n_drafts=1, judge=judge, draft_fn=draft_fn, max_workers=1, db_path=seeded_db,
    )
    assert calls["n"] == 2  # one draft per prompt
    assert len(comp["runs"]) == 2
    assert {r["prompt_name"] for r in comp["runs"]} == {"draft_sale", "draft_sale_v2"}
    assert comp["runs"][0]["prompt_type"] == "baseline"
    assert "draft_text" not in comp["runs"][0]  # excluded from default payload
    assert comp["n_drafts"] == 1


def test_run_compare_n_drafts_creates_more_runs(seeded_db: Path):
    _seed_area(seeded_db)
    draft_fn, _ = _draft_fn_tracker()
    # 2 prompts x 2 drafts x 2 criteria = 8 verdicts
    judge = FakeJudge(verdicts=[True, True, False, False, True, False, True, False])
    prompts = load_prompts(["draft_sale", "draft_sale_v2"], db_path=seeded_db)

    comp = run_compare(
        "sale", "contract_sale_v1", "task", prompts,
        n_drafts=2, judge=judge, draft_fn=draft_fn, max_workers=1, db_path=seeded_db,
    )
    assert len(comp["runs"]) == 4  # 2 prompts x 2 drafts
    assert comp["n_drafts"] == 2


def test_build_matrix_n1_verdicts(seeded_db: Path):
    _seed_area(seeded_db)
    draft_fn, _ = _draft_fn_tracker()
    judge = FakeJudge(verdicts=[True, False, False, True])
    prompts = load_prompts(["draft_sale", "draft_sale_v2"], db_path=seeded_db)
    comp = run_compare("sale", "contract_sale_v1", "task", prompts,
                       n_drafts=1, judge=judge, draft_fn=draft_fn, max_workers=1, db_path=seeded_db)

    m = build_matrix(comp)
    assert [c["id"] for c in m["criteria"]] == ["party_id", "price"]
    assert [c["prompt_type"] for c in m["columns"]] == ["baseline", "experimental"]
    assert m["cells"]["draft_sale"]["party_id"]["verdict"] == "pass"
    assert m["cells"]["draft_sale"]["price"]["verdict"] == "fail"


def test_build_matrix_n_gt_1_pass_rate(seeded_db: Path):
    _seed_area(seeded_db)
    draft_fn, _ = _draft_fn_tracker()
    # 2 prompts x 2 drafts x 2 criteria = 8 verdicts, ordered:
    #   draft_sale:   d1(party=T, price=F), d2(party=T, price=F)
    #   draft_sale_v2: d1(party=F, price=T), d2(party=F, price=T)
    judge = FakeJudge(verdicts=[True, False, True, False, False, True, False, True])
    prompts = load_prompts(["draft_sale", "draft_sale_v2"], db_path=seeded_db)
    comp = run_compare("sale", "contract_sale_v1", "task", prompts,
                       n_drafts=2, judge=judge, draft_fn=draft_fn, max_workers=1, db_path=seeded_db)

    m = build_matrix(comp)
    cell = m["cells"]["draft_sale"]["party_id"]
    assert "verdict" not in cell
    assert cell["n"] == 2
    assert cell["n_pass"] == 2
    assert cell["pass_rate"] == 1.0
    # cross-check: draft_sale price fails both drafts
    assert m["cells"]["draft_sale"]["price"]["n_pass"] == 0


def test_run_compare_rejects_too_few_prompts(seeded_db: Path):
    _seed_area(seeded_db)
    prompts = load_prompts(["draft_sale"], db_path=seeded_db)
    with pytest.raises(ValidationError):
        run_compare("sale", "contract_sale_v1", "task", prompts, db_path=seeded_db)


def test_run_compare_rejects_bad_mode(seeded_db: Path):
    _seed_area(seeded_db)
    prompts = load_prompts(["draft_sale", "draft_sale_v2"], db_path=seeded_db)
    with pytest.raises(ValidationError):
        run_compare("sale", "contract_sale_v1", "task", prompts, mode="full-crew", db_path=seeded_db)


def test_run_compare_rejects_unknown_rubric(seeded_db: Path):
    _seed_area(seeded_db)
    prompts = load_prompts(["draft_sale", "draft_sale_v2"], db_path=seeded_db)
    draft_fn, _ = _draft_fn_tracker()
    with pytest.raises(KeyError):
        run_compare("sale", "no_such_rubric", "task", prompts,
                    draft_fn=draft_fn, judge=FakeJudge([True, False]), db_path=seeded_db)


def test_load_prompts_missing_raises(seeded_db: Path):
    _seed_area(seeded_db)
    with pytest.raises(Exception):
        load_prompts(["draft_sale", "nope"], db_path=seeded_db)
