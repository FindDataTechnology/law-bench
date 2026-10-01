"""Tests for ``contract_evaluate`` / ``rubric_list`` / ``run_list`` / ``run_get``.

Hermetic: the wrapped ``src.eval`` functions are monkeypatched (no LLM judge, no
DB). Verifies file-or-text dispatch, ``no_store`` behavior, error propagation,
and the list helpers.
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


def _eval_result(**over):
    base = {
        "rubric": "contract_drafting_v1",
        "score": 1.0,
        "max_score": 1.0,
        "all_pass": True,
        "n_criteria": 2,
        "n_passed": 2,
        "summary": "2/2 criteria passed. ALL PASS.",
        "criteria_results": [
            {"id": "c1", "title": "t", "verdict": "pass", "reasoning": ""}
        ],
        "judge_model": "ark",
        "scored_at": "2026-07-31T00:00:00Z",
    }
    base.update(over)
    return base


async def test_inline_text_no_store(monkeypatch):
    import src.eval.scoring as scoring_mod
    import src.eval.store as store_mod

    calls = {}

    def fake_eval(contract_text, rubric_name, task_desc=None, verbose=False):
        calls.update(text=contract_text, rubric=rubric_name, task=task_desc, verbose=verbose)
        return _eval_result()

    store_calls: list = []
    monkeypatch.setattr(scoring_mod, "evaluate_contract", fake_eval)
    monkeypatch.setattr(store_mod, "store_result", lambda *a, **k: store_calls.append((a, k)) or 1)

    from fd_coding_law_bench_mcp.tools.evaluate import contract_evaluate

    res = await contract_evaluate("# 服务协议\n甲方...", "contract_drafting_v1", task="起草", no_store=True)
    assert calls["text"].startswith("# 服务协议")
    assert calls["rubric"] == "contract_drafting_v1"
    assert calls["task"] == "起草"
    assert store_calls == []  # no_store -> nothing persisted
    assert res["all_pass"] is True
    assert res["criteria_results"][0]["verdict"] == "pass"


async def test_file_path_is_read_and_stored(monkeypatch, tmp_path):
    import src.eval.scoring as scoring_mod
    import src.eval.store as store_mod

    draft = tmp_path / "draft.md"
    draft.write_text("# 合同正文", encoding="utf-8")

    seen = {}

    def fake_eval(contract_text, rubric_name, task_desc=None, verbose=False):
        seen["text"] = contract_text
        return _eval_result()

    store_args = {}

    def fake_store(result, contract_path=None, task_desc=None):
        store_args.update(contract_path=contract_path, task_desc=task_desc)
        return 42

    monkeypatch.setattr(scoring_mod, "evaluate_contract", fake_eval)
    monkeypatch.setattr(store_mod, "store_result", fake_store)

    from fd_coding_law_bench_mcp.tools.evaluate import contract_evaluate

    await contract_evaluate(str(draft), "contract_drafting_v1", task="t")
    assert seen["text"] == "# 合同正文"
    assert store_args["contract_path"] == str(draft)
    assert store_args["task_desc"] == "t"


async def test_missing_rubric_propagates(monkeypatch):
    import src.eval.scoring as scoring_mod

    def boom(contract_text, rubric_name, task_desc=None, verbose=False):
        raise KeyError(f"Rubric not found: {rubric_name!r}")

    monkeypatch.setattr(scoring_mod, "evaluate_contract", boom)

    from fd_coding_law_bench_mcp.tools.evaluate import contract_evaluate

    with pytest.raises(KeyError):
        await contract_evaluate("some text", "not_a_rubric")


async def test_list_rubrics_and_runs(monkeypatch):
    import src.eval.rubric as rubric_mod
    import src.eval.store as store_mod

    monkeypatch.setattr(
        rubric_mod,
        "list_rubrics",
        lambda db_path=None: [{"name": "r1", "context": "check", "source": "s"}],
    )
    monkeypatch.setattr(store_mod, "list_runs", lambda limit=20, db_path=None: [{"id": 1}])

    from fd_coding_law_bench_mcp.tools.evaluate import rubric_list, run_list

    assert await rubric_list() == [{"name": "r1", "context": "check", "source": "s"}]
    assert await run_list(limit=5) == [{"id": 1}]


async def test_list_rubrics_include_counts_routes_to_with_counts(monkeypatch):
    import src.eval.rubric_crud as rc

    enriched = [{
        "id": 1, "name": "r1", "context": "check", "source": "local",
        "source_path": None, "description": "d",
        "created_at": "2026-01-01T00:00:00+00:00",
        "criterion_count": 3, "is_harbor": False,
    }]
    monkeypatch.setattr(rc, "list_rubrics_with_counts", lambda: enriched)

    from fd_coding_law_bench_mcp.tools.evaluate import rubric_list

    out = await rubric_list(include_counts=True)
    assert out == enriched
    assert out[0]["criterion_count"] == 3
    assert out[0]["is_harbor"] is False


async def test_list_rubrics_default_ignores_counts(monkeypatch):
    import src.eval.rubric as rubric_mod

    monkeypatch.setattr(
        rubric_mod, "list_rubrics",
        lambda db_path=None: [{"name": "r1", "context": "check", "source": "s"}],
    )

    from fd_coding_law_bench_mcp.tools.evaluate import rubric_list

    out = await rubric_list()
    assert out == [{"name": "r1", "context": "check", "source": "s"}]


async def test_get_run_detail_returns_fields_and_criteria(monkeypatch):
    import src.eval.store as store_mod

    monkeypatch.setattr(
        store_mod, "get_run",
        lambda run_id: {
            "id": run_id, "rubric_name": "contract_sale_v1", "score": 0.0,
            "max_score": 1.0, "all_pass": 0, "n_criteria": 2, "n_passed": 1,
            "criteria_results": [
                {"criterion_id": "c1", "title": "t1", "verdict": "pass", "reasoning": "", "ordinal": 0},
                {"criterion_id": "c2", "title": "t2", "verdict": "fail", "reasoning": "no", "ordinal": 1},
            ],
        },
    )

    from fd_coding_law_bench_mcp.tools.evaluate import run_get

    out = await run_get(42)
    assert out["id"] == 42
    assert [c["criterion_id"] for c in out["criteria_results"]] == ["c1", "c2"]


async def test_get_run_detail_unknown_raises(monkeypatch):
    import src.eval.store as store_mod

    def boom(run_id):
        raise KeyError(f"Run not found: {run_id}")

    monkeypatch.setattr(store_mod, "get_run", boom)

    from fd_coding_law_bench_mcp.tools.evaluate import run_get

    with pytest.raises(KeyError):
        await run_get(999999)


# --- add-contract-pipeline: run_id ---

async def test_run_id_returned_when_stored(monkeypatch, tmp_path):
    import src.eval.scoring as scoring_mod
    import src.eval.store as store_mod

    monkeypatch.setattr(
        scoring_mod, "evaluate_contract",
        lambda text, rubric, task_desc=None, verbose=False: _eval_result(),
    )
    monkeypatch.setattr(store_mod, "store_result", lambda *a, **k: 42)

    from fd_coding_law_bench_mcp.tools.evaluate import contract_evaluate

    res = await contract_evaluate("正文", "contract_drafting_v1")
    assert res["run_id"] == 42


async def test_run_id_null_when_no_store(monkeypatch):
    import src.eval.scoring as scoring_mod
    import src.eval.store as store_mod

    monkeypatch.setattr(
        scoring_mod, "evaluate_contract",
        lambda text, rubric, task_desc=None, verbose=False: _eval_result(),
    )
    monkeypatch.setattr(store_mod, "store_result", lambda *a, **k: 1)

    from fd_coding_law_bench_mcp.tools.evaluate import contract_evaluate

    res = await contract_evaluate("正文", "contract_drafting_v1", no_store=True)
    assert res["run_id"] is None


async def test_long_inline_text_does_not_crash_stat(monkeypatch):
    """A full contract body passed inline must be treated as text, not stat-ed."""
    import src.eval.scoring as scoring_mod
    import src.eval.store as store_mod

    seen = {}
    long_body = "## 当事人\n甲方：" + ("x" * 5000)

    def fake_eval(contract_text, rubric_name, task_desc=None, verbose=False):
        seen["text"] = contract_text
        return _eval_result()

    monkeypatch.setattr(scoring_mod, "evaluate_contract", fake_eval)
    monkeypatch.setattr(store_mod, "store_result", lambda *a, **k: 1)

    from fd_coding_law_bench_mcp.tools.evaluate import contract_evaluate

    res = await contract_evaluate(long_body, "contract_drafting_v1", no_store=True)
    assert seen["text"] == long_body
    assert res["run_id"] is None
