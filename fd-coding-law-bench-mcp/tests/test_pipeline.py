"""Tests for the contract pipeline tools + LangGraph flow.

Hermetic: the MCP tool functions, the fill/improve LLM, and ``pipeline_store``
are monkeypatched (no DB / LLM / langgraph network). Verifies the tool summary
extraction, the rubric default, the fill cache hit/miss, and the graph's
happy-path + self-heal loop.
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


# --- MCP tool: pipeline_run summary extraction ---


async def test_pipeline_run_returns_summary(monkeypatch):
    import fd_coding_law_bench_mcp.pipeline.graph as graph_mod

    fake_state = {
        "pipeline_run_id": 7,
        "eval_run_id": 99,
        "iteration": 2,
        "actions_taken": [{"iteration": 1, "excluded": [420]}],
        "recommendations": [{"clause_id": 420, "action": "reject", "reason": "thin"}],
        "best": {
            "iteration": 2,
            "eval_run_id": 99,
            "fill_cache_id": 3,
            "fill_temperature": 0.0,
            "eval_result": {
                "score": 0.8, "max_score": 1.0, "all_pass": False,
                "n_passed": 8, "n_criteria": 10, "summary": "8/10",
            },
        },
    }
    monkeypatch.setattr(graph_mod, "run_pipeline", lambda *a, **k: fake_state)

    from fd_coding_law_bench_mcp.tools.pipeline import pipeline_run

    out = await pipeline_run("sale", tags={"scenario": "农产品买卖", "stance": "balanced"})
    assert out["pipeline_run_id"] == 7
    assert out["eval_run_id"] == 99
    assert out["iteration"] == 2
    assert out["n_passed"] == 8
    assert out["recommendations"][0]["clause_id"] == 420


# --- MCP tools: list / get ---


async def test_pipeline_list_delegates(monkeypatch):
    import src.eval.pipeline_store as ps

    monkeypatch.setattr(ps, "list_pipeline_runs", lambda limit=20: [{"id": 1}])

    from fd_coding_law_bench_mcp.tools.pipeline import pipeline_list

    assert await pipeline_list(limit=5) == [{"id": 1}]


async def test_pipeline_get_joins_criteria(monkeypatch):
    import src.eval.pipeline_store as ps
    import src.eval.store as store_mod

    monkeypatch.setattr(ps, "get_pipeline_run", lambda pid: {
        "id": pid, "contract_type": "sale", "filled_text": "正文",
        "fill_values": {"party_a": "甲"}, "all_pass": 1, "eval_run_id": 42,
        "actions_taken": [], "recommendations": [], "fill_temperature": 0.0,
    })
    monkeypatch.setattr(store_mod, "get_run", lambda rid: {
        "id": rid, "criteria_results": [{"criterion_id": "c1", "verdict": "pass", "ordinal": 0}],
    })

    from fd_coding_law_bench_mcp.tools.pipeline import pipeline_get

    out = await pipeline_get(7)
    assert out["all_pass"] is True  # int -> bool
    assert out["criteria_results"][0]["verdict"] == "pass"


async def test_pipeline_get_unknown_raises(monkeypatch):
    import src.eval.pipeline_store as ps
    from src.eval.errors import NotFoundError

    monkeypatch.setattr(ps, "get_pipeline_run", lambda pid: None)

    from fd_coding_law_bench_mcp.tools.pipeline import pipeline_get

    with pytest.raises(NotFoundError):
        await pipeline_get(999)


# --- rubric latest-version default ---


async def test_default_rubric_latest_version(monkeypatch):
    import src.eval.rubric as rubric_mod

    monkeypatch.setattr(rubric_mod, "list_rubrics", lambda db_path=None: [
        {"name": "contract_sale_v1", "context": "contract", "source": "local"},
        {"name": "contract_sale_v2", "context": "contract", "source": "local"},
        {"name": "contract_employment_v1", "context": "contract", "source": "local"},
    ])

    from fd_coding_law_bench_mcp.pipeline.graph import default_rubric

    assert default_rubric("sale") == "contract_sale_v2"


async def test_default_rubric_missing_raises(monkeypatch):
    import src.eval.rubric as rubric_mod
    from src.eval.errors import NotFoundError

    monkeypatch.setattr(rubric_mod, "list_rubrics", lambda db_path=None: [
        {"name": "contract_sale_v1", "context": "contract", "source": "local"},
    ])

    from fd_coding_law_bench_mcp.pipeline.graph import default_rubric

    with pytest.raises(NotFoundError):
        default_rubric("nope")


# --- fill cache ---


async def test_fill_cache_hit_skips_llm(monkeypatch):
    import fd_coding_law_bench_mcp.pipeline.fill as fill_mod

    called = {"llm": 0, "insert": 0}

    monkeypatch.setattr(fill_mod, "lookup_fill", lambda key: {
        "id": 5, "fill_values": {"party_a": "甲"}, "temperature": 0.0, "model": "m",
    })
    monkeypatch.setattr(fill_mod, "_call_llm", lambda prompt, temperature: called.__setitem__("llm", called["llm"] + 1) or ("{}", "m"))
    monkeypatch.setattr(fill_mod, "insert_fill", lambda *a, **k: called.__setitem__("insert", called["insert"] + 1) or 5)

    from fd_coding_law_bench_mcp.pipeline.fill import fill_slots

    out = fill_slots("sale", "农产品买卖", ["party_a"], [{"name": "party_a"}], 0.0)
    assert out["hit"] is True
    assert out["fill_values"] == {"party_a": "甲"}
    assert called["llm"] == 0
    assert called["insert"] == 0


async def test_fill_cache_miss_calls_llm_and_records_temperature(monkeypatch):
    import fd_coding_law_bench_mcp.pipeline.fill as fill_mod

    captured = {}

    monkeypatch.setattr(fill_mod, "lookup_fill", lambda key: None)
    monkeypatch.setattr(fill_mod, "_call_llm", lambda prompt, temperature: ('{"party_a": "北京甲科技有限公司"}', "doubao"))
    monkeypatch.setattr(fill_mod, "insert_fill", lambda key, ct, sc, sh, fv, t, m: captured.update(t=t, m=m) or 9)

    from fd_coding_law_bench_mcp.pipeline.fill import fill_slots

    out = fill_slots("sale", "农产品买卖", ["party_a"], [{"name": "party_a"}], 0.0)
    assert out["hit"] is False
    assert out["fill_values"] == {"party_a": "北京甲科技有限公司"}
    assert out["fill_cache_id"] == 9
    assert captured["t"] == 0.0
    assert captured["m"] == "doubao"


async def test_render_filled_leaves_unfilled():
    from fd_coding_law_bench_mcp.pipeline.fill import render_filled

    filled, unfilled = render_filled("甲方：{{party_a}} 乙方：{{party_b}}", {"party_a": "甲"})
    assert "甲" in filled
    assert "{{party_b}}" in filled
    assert unfilled == ["party_b"]


# --- graph flow ---


def _patch_graph_deps(monkeypatch, *, eval_results, customs=None, diagnose_out=None):
    """Monkeypatch the node dependencies the compiled graph calls at invoke time."""
    import fd_coding_law_bench_mcp.tools.generate as gen_mod
    import fd_coding_law_bench_mcp.tools.evaluate as ev_mod
    import fd_coding_law_bench_mcp.pipeline.fill as fill_mod
    import fd_coding_law_bench_mcp.pipeline.improve as imp_mod
    import fd_coding_law_bench_mcp.pipeline.graph as graph_mod
    import src.eval.pipeline_store as ps

    monkeypatch.setattr(gen_mod, "contract_generate", lambda *a, **k: {
        "body_text": "## 当事人\n甲方：{{party_a}}", "slots": ["party_a"],
        "instructions": [{"name": "party_a", "label": "甲方", "description": "", "example": "甲", "required": True}],
    })
    monkeypatch.setattr(fill_mod, "fill_slots", lambda *a, **k: {
        "fill_values": {"party_a": "北京甲科技有限公司"}, "fill_cache_id": 1,
        "temperature": 0.0, "model": "m",
    })
    monkeypatch.setattr(fill_mod, "render_filled", lambda body, fv: (body.replace("{{party_a}}", "北京甲科技有限公司"), []))

    results = list(eval_results)

    def fake_eval(contract, rubric, task_desc=None):
        return results.pop(0)
    monkeypatch.setattr(ev_mod, "contract_evaluate", fake_eval)

    monkeypatch.setattr(graph_mod, "_current_customs", lambda ct, stance: customs or [])
    monkeypatch.setattr(imp_mod, "diagnose", lambda *a, **k: diagnose_out or {"exclude_custom_clause_ids": [], "recommendations": []})
    monkeypatch.setattr(ps, "insert_pipeline_run", lambda row: 7)


async def test_graph_happy_path_stops_at_iteration_1(monkeypatch):
    _patch_graph_deps(monkeypatch, eval_results=[{
        "all_pass": True, "n_passed": 2, "n_criteria": 2, "score": 1.0, "max_score": 1.0,
        "criteria_results": [{"verdict": "pass", "title": "t"}], "run_id": 99, "summary": "2/2",
    }])

    from fd_coding_law_bench_mcp.pipeline.graph import run_pipeline

    state = run_pipeline("sale", tags={"scenario": "农产品买卖", "stance": "balanced"}, rubric="contract_sale_v2")
    assert state["pipeline_run_id"] == 7
    assert state["iteration"] == 1
    assert state["best"]["iteration"] == 1
    assert state["actions_taken"] == []
    assert state["eval_run_id"] == 99


async def test_graph_loop_records_recommendations(monkeypatch):
    fail = {
        "all_pass": False, "n_passed": 1, "n_criteria": 2, "score": 0.5, "max_score": 1.0,
        "criteria_results": [{"verdict": "fail", "title": "检验期间", "reasoning": "missing"}],
        "run_id": 100, "summary": "1/2",
    }
    ok = {
        "all_pass": True, "n_passed": 2, "n_criteria": 2, "score": 1.0, "max_score": 1.0,
        "criteria_results": [{"verdict": "pass", "title": "t"}], "run_id": 101, "summary": "2/2",
    }
    _patch_graph_deps(
        monkeypatch,
        eval_results=[fail, ok],
        customs=[{"id": 420, "section": "权利义务", "body": "thin risk transfer"}],
        diagnose_out={
            "exclude_custom_clause_ids": [420],
            "recommendations": [{"clause_id": 420, "action": "reject", "reason": "thin override"}],
        },
    )

    from fd_coding_law_bench_mcp.pipeline.graph import run_pipeline

    state = run_pipeline("sale", tags={"scenario": "农产品买卖", "stance": "balanced"}, rubric="contract_sale_v2", max_iterations=3)
    assert state["iteration"] == 2  # improved once, then passed
    assert state["best"]["iteration"] == 2
    assert state["best"]["eval_run_id"] == 101  # the passing (best) run
    assert len(state["actions_taken"]) == 1
    assert state["actions_taken"][0]["excluded"] == [420]
    assert state["recommendations"][0]["clause_id"] == 420
    assert state["pipeline_run_id"] == 7
