"""Concurrency tests for ``src/eval/compare.py::run_compare``.

Covers the ``prompt-compare`` concurrency delta: default sequential behavior,
bounded in-flight drafts, deterministic persistence order at any concurrency,
and the [1, 8] clamp with ``effective_concurrency`` reporting (design D3/D4).

Runs fully offline like ``test_compare.py``: injected ``draft_fn`` +
``FakeJudge``. The in-flight bound is observed with a lock-guarded counter
widened by a short sleep; the counter's upper bound (never exceed N) is the
spec guarantee, the lower bound (>= 2 at concurrency >= 2) just confirms real
overlap between pool threads.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from src.eval.compare import load_prompts, run_compare
from src.eval.manage import create_prompt, create_rubric
from src.eval.store import ensure_schema, get_run_draft

from _fakes import FakeJudge

_PROMPTS = ["draft_sale", "draft_sale_v2"]


def _seed_area(db) -> None:
    """One rubric (2 criteria) + two sale prompts, mirroring test_compare.py."""
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
    create_prompt("draft_sale", "sale", "drafting", "draft a sale contract", "c1",
                  "baseline", db_path=db)
    create_prompt("draft_sale_v2", "sale", "drafting", "draft a better sale contract",
                  "c2", "experimental", db_path=db)


def _counting_draft_fn(window_s: float = 0.15):
    """Drafter double tracking in-flight calls; returns (fn, max_in_flight)."""
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    def fn(task: str, content: str, templates: str) -> str:
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(window_s)
        with lock:
            state["current"] -= 1
        return f"DRAFT::{content}"

    return fn, state


def _judge_for(n_drafts: int) -> FakeJudge:
    # 2 prompts x n_drafts x 2 criteria verdicts, all pass
    return FakeJudge(verdicts=[True] * (2 * n_drafts * 2), model_name="fake-judge")


def _run(db, *, n_drafts=1, concurrency=None, draft_fn=None) -> dict:
    prompts = load_prompts(_PROMPTS, db_path=db)
    kw = (
        {"concurrency": concurrency} if concurrency is not None else {}
    )
    return run_compare(
        "sale", "contract_sale_v1", "task", prompts,
        n_drafts=n_drafts, judge=_judge_for(n_drafts),
        draft_fn=draft_fn, max_workers=1, db_path=db, **kw,
    )


def test_default_is_sequential_and_reports_effective_1(seeded_db: Path):
    _seed_area(seeded_db)
    fn, state = _counting_draft_fn()
    comp = _run(seeded_db, n_drafts=2, draft_fn=fn)
    assert state["max"] == 1  # no concurrency without the knob
    assert comp["effective_concurrency"] == 1
    assert len(comp["runs"]) == 4


def test_bounded_in_flight_drafts(seeded_db: Path):
    _seed_area(seeded_db)
    fn, state = _counting_draft_fn()
    comp = _run(seeded_db, n_drafts=3, concurrency=4, draft_fn=fn)  # 6 jobs
    assert state["max"] <= 4  # spec guarantee: never exceed the bound
    assert state["max"] >= 2  # real overlap between pool threads
    assert comp["effective_concurrency"] == 4


def test_persisted_order_identical_to_sequential(seeded_db: Path):
    _seed_area(seeded_db)
    # Deterministic per-prompt draft text so run identity is comparable.
    fn, _state = _counting_draft_fn(window_s=0.0)
    seq = _run(seeded_db, n_drafts=2, concurrency=1, draft_fn=fn)
    par = _run(seeded_db, n_drafts=2, concurrency=4, draft_fn=fn)

    def _identity(comp: dict) -> list[tuple]:
        return [
            (r["prompt_name"], get_run_draft(comp["id"], r["id"], db_path=seeded_db)["draft_text"])
            for r in comp["runs"]
        ]

    assert _identity(seq) == _identity(par)
    # prompt-major order: both drafts of prompt 1 before prompt 2
    assert [r["prompt_name"] for r in par["runs"]] == [
        "draft_sale", "draft_sale", "draft_sale_v2", "draft_sale_v2",
    ]


def test_oversized_concurrency_clamps_to_8(seeded_db: Path):
    _seed_area(seeded_db)
    fn, state = _counting_draft_fn()
    comp = _run(seeded_db, n_drafts=2, concurrency=20, draft_fn=fn)
    assert comp["effective_concurrency"] == 8
    assert state["max"] <= 8
    assert len(comp["runs"]) == 4  # compare still succeeds post-clamp


def test_non_positive_concurrency_clamps_to_1(seeded_db: Path):
    _seed_area(seeded_db)
    fn, _state = _counting_draft_fn(window_s=0.0)
    comp = _run(seeded_db, n_drafts=1, concurrency=0, draft_fn=fn)
    assert comp["effective_concurrency"] == 1
