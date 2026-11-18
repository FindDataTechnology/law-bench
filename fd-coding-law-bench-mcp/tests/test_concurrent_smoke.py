"""Concurrent smoke test: verify async tools run in parallel, not serially.

This script fires `pipeline_run`, `contract_evaluate`, and `clause_list` in
parallel via `asyncio.gather` and measures wall-clock time. If the tools are
truly async (not blocking the event loop), the total time should be closer to
the slowest call than the sum of all three.

Hermetic: all `src.*` functions are monkeypatched to simulate slow I/O (1s each).
"""

from __future__ import annotations

import asyncio
import time

import pytest

pytestmark = pytest.mark.asyncio


async def test_concurrent_tools_run_in_parallel(monkeypatch):
    """Verify that async tools run concurrently, not serially."""
    import fd_coding_law_bench_mcp.pipeline.graph as graph_mod
    import src.clauses.store as clauses_store
    import src.eval.scoring as scoring_mod
    import src.eval.store as eval_store

    # Monkeypatch to simulate slow I/O (1s each)
    def fake_run_pipeline(*args, **kwargs):
        time.sleep(1)
        return {
            "pipeline_run_id": 1,
            "eval_run_id": 2,
            "iteration": 1,
            "actions_taken": [],
            "recommendations": [],
            "best": {
                "iteration": 1,
                "eval_run_id": 2,
                "eval_result": {
                    "score": 1.0,
                    "max_score": 1.0,
                    "all_pass": True,
                    "n_passed": 2,
                    "n_criteria": 2,
                    "summary": "2/2",
                },
            },
        }

    def fake_evaluate_contract(*args, **kwargs):
        time.sleep(1)
        return {
            "rubric": "test",
            "score": 1.0,
            "max_score": 1.0,
            "all_pass": True,
            "n_criteria": 2,
            "n_passed": 2,
            "summary": "2/2",
            "criteria_results": [],
            "judge_model": "test",
            "scored_at": "2026-01-01T00:00:00Z",
        }

    def fake_list_clauses(*args, **kwargs):
        time.sleep(1)
        return [{"id": 1}]

    monkeypatch.setattr(graph_mod, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(scoring_mod, "evaluate_contract", fake_evaluate_contract)
    monkeypatch.setattr(clauses_store, "list_clauses", fake_list_clauses)
    monkeypatch.setattr(eval_store, "store_result", lambda *a, **k: 1)

    from fd_coding_law_bench_mcp.tools.clauses import clause_list
    from fd_coding_law_bench_mcp.tools.evaluate import contract_evaluate
    from fd_coding_law_bench_mcp.tools.pipeline import pipeline_run

    start = time.time()
    results = await asyncio.gather(
        pipeline_run("sale"),
        contract_evaluate("text", "rubric"),
        clause_list("sale"),
    )
    elapsed = time.time() - start

    # If serial: ~3s. If parallel: ~1s. Allow 1.5s for overhead.
    assert elapsed < 1.5, f"Tools ran serially ({elapsed:.2f}s); expected parallel (~1s)"
    assert len(results) == 3
    print(f"✓ Concurrent test passed: {elapsed:.2f}s (parallel, not serial ~3s)")
