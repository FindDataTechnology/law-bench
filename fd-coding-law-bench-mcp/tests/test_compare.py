"""Tests for the compare orchestration + read tools.

Hermetic: ``src.eval.compare`` and ``src.eval.store`` are monkeypatched (no LLM,
no DB). Verifies name-resolution + delegation, the <2-prompt guard, and the read
helpers.
"""

from __future__ import annotations

import pytest

from src.eval.errors import ValidationError

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


def _prompt(name, ptype="baseline"):
    return {"id": 1, "name": name, "content": "draft...", "prompt_type": ptype}


def _compare(**over):
    base = {
        "id": 7,
        "label": "sale test",
        "contract_type": "sale",
        "rubric_name": "contract_sale_v1",
        "task_desc": "task",
        "gen_mode": "drafter-only",
        "n_drafts": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "runs": [],
    }
    base.update(over)
    return base


async def test_run_compare_resolves_names_and_delegates(monkeypatch):
    import src.eval.compare as cmp

    seen = {}

    def fake_load(names):
        seen["names"] = names
        return [_prompt("draft_sale"), _prompt("draft_sale_v2")]

    def fake_run(contract_type, rubric_name, task_desc, prompts, mode="drafter-only",
                 n_drafts=1, concurrency=1, label=None):
        seen.update(contract_type=contract_type, rubric=rubric_name, task=task_desc,
                    prompts=prompts, mode=mode, n_drafts=n_drafts, label=label,
                    concurrency=concurrency)
        return _compare()

    monkeypatch.setattr(cmp, "load_prompts", fake_load)
    monkeypatch.setattr(cmp, "run_compare", fake_run)

    from fd_coding_law_bench_mcp.tools.compare import compare_run

    out = await compare_run("sale", "contract_sale_v1", "task",
                      ["draft_sale", "draft_sale_v2"], n_drafts=2, label="lbl")
    assert seen["names"] == ["draft_sale", "draft_sale_v2"]
    assert seen["mode"] == "drafter-only"
    assert seen["n_drafts"] == 2
    assert seen["label"] == "lbl"
    assert seen["concurrency"] == 1  # default passes through
    assert [p["name"] for p in seen["prompts"]] == ["draft_sale", "draft_sale_v2"]
    assert out["id"] == 7


async def test_run_compare_passes_concurrency_through(monkeypatch):
    """An explicit concurrency reaches run_compare; the result (with the
    service-computed effective_concurrency) is returned to the caller."""
    import src.eval.compare as cmp

    seen = {}

    def fake_load(names):
        return [_prompt("a"), _prompt("b")]

    def fake_run(contract_type, rubric_name, task_desc, prompts, mode="drafter-only",
                 n_drafts=1, concurrency=1, label=None):
        seen["concurrency"] = concurrency
        # mirrors the real clamp: 20 -> 8
        return _compare(effective_concurrency=max(1, min(concurrency, 8)))

    monkeypatch.setattr(cmp, "load_prompts", fake_load)
    monkeypatch.setattr(cmp, "run_compare", fake_run)

    from fd_coding_law_bench_mcp.tools.compare import compare_run

    out = await compare_run("sale", "contract_sale_v1", "task",
                            ["a", "b"], n_drafts=2, concurrency=4)
    assert seen["concurrency"] == 4
    assert out["effective_concurrency"] == 4


async def test_run_compare_oversized_concurrency_still_succeeds(monkeypatch):
    """The tool does not validate the bound - the service clamp keeps the call
    succeeding, with the effective value surfaced in the result."""
    import src.eval.compare as cmp

    def fake_load(names):
        return [_prompt("a"), _prompt("b")]

    def fake_run(contract_type, rubric_name, task_desc, prompts, mode="drafter-only",
                 n_drafts=1, concurrency=1, label=None):
        return _compare(effective_concurrency=max(1, min(concurrency, 8)))

    monkeypatch.setattr(cmp, "load_prompts", fake_load)
    monkeypatch.setattr(cmp, "run_compare", fake_run)

    from fd_coding_law_bench_mcp.tools.compare import compare_run

    out = await compare_run("sale", "contract_sale_v1", "task",
                            ["a", "b"], concurrency=50)
    assert out["id"] == 7  # succeeded, not an error
    assert out["effective_concurrency"] == 8


async def test_run_compare_fewer_than_two_prompts_raises(monkeypatch):
    """The wrapped run_compare raises ValidationError before any LLM/DB call."""
    import src.eval.compare as cmp

    monkeypatch.setattr(cmp, "load_prompts", lambda names: [_prompt("only_one")])

    from fd_coding_law_bench_mcp.tools.compare import compare_run

    with pytest.raises(ValidationError):
        await compare_run("sale", "contract_sale_v1", "task", ["only_one"])


async def test_list_compares_delegates(monkeypatch):
    import src.eval.store as store

    monkeypatch.setattr(store, "list_compares", lambda limit=20: [_compare()])

    from fd_coding_law_bench_mcp.tools.compare import compare_list

    out = await compare_list(limit=5)
    assert len(out) == 1 and out[0]["id"] == 7


async def test_get_compare_unknown_raises(monkeypatch):
    import src.eval.store as store

    def boom(compare_id):
        raise KeyError(f"Compare not found: {compare_id}")

    monkeypatch.setattr(store, "get_compare", boom)

    from fd_coding_law_bench_mcp.tools.compare import compare_get

    with pytest.raises(KeyError):
        await compare_get(999)


async def test_get_compare_matrix_builds_from_compare(monkeypatch):
    import src.eval.compare as cmp
    import src.eval.store as store

    received = {}
    matrix = {"criteria": [{"id": "c1"}], "columns": [], "cells": {}, "n_drafts": 1}

    monkeypatch.setattr(store, "get_compare", lambda cid: _compare(id=cid))

    def fake_build(compare):
        received["compare_id"] = compare["id"]
        return matrix

    monkeypatch.setattr(cmp, "build_matrix", fake_build)

    from fd_coding_law_bench_mcp.tools.compare import compare_matrix

    out = await compare_matrix(7)
    assert out == matrix
    assert received["compare_id"] == 7


async def test_get_run_draft_delegates(monkeypatch):
    import src.eval.store as store

    monkeypatch.setattr(
        store, "get_run_draft",
        lambda compare_id, run_id: {"run_id": run_id, "prompt_name": "p", "draft_text": "DRAFT"},
    )

    from fd_coding_law_bench_mcp.tools.compare import run_draft

    out = await run_draft(7, 42)
    assert out == {"run_id": 42, "prompt_name": "p", "draft_text": "DRAFT"}
