"""MCP tool behavior annotations (mcp-tool-annotations).

Three things must hold, or a client's auto-approval policy is built on sand:

1. **Complete** - every registered tool carries all four hints. A missing flag
   forces the client to guess.
2. **Honest** - a tool that writes persistent state is never marked read-only.
   The expected-write set below is written by hand on purpose: it is what
   catches an implementation whose side effects changed while the declaration
   did not.
3. **One table** - the runtime registry and ``annotations.TOOL_ANNOTATIONS``
   are exactly the same set. A new ``@mcp.tool`` that forgets to register its
   hints fails here rather than shipping a silent default.

``openWorldHint`` is asserted separately: the LLM-backed tools (draft, judge,
fill, retag) must be open-world; pure DB reads must not be.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

# The shared venv also has an editable install of this package pointing at
# another checkout; put this repo's sub-project first so the test asserts
# against the code under test.
_PKG_SRC = Path(__file__).resolve().parents[1] / "fd-coding-law-bench-mcp" / "src"
if str(_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_PKG_SRC))

from fd_coding_law_bench_mcp.annotations import TOOL_ANNOTATIONS, annotations_for  # noqa: E402
from fd_coding_law_bench_mcp.server import mcp  # noqa: E402

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

MANIFEST = Path(__file__).resolve().parents[1] / "tool-surface.json"

#: Tools that persist state. Hand-written expectation, not derived from the
#: annotation table - that is the point.
WRITES_STATE = {
    "agent_run_store",
    "auto_reject_pipeline_run",
    "clause_delete",
    "clause_review",
    "clause_update",
    "compare_run",
    "contract_evaluate",
    "contract_generate",
    "contract_generate_batch",
    "contract_generate_stored",
    "contract_content",
    "criterion_add",
    "criterion_delete",
    "criterion_reorder",
    "criterion_update",
    "prompt_create",
    "prompt_delete",
    "prompt_update",
    "rubric_create",
    "rubric_delete",
    "rubric_update",
    "self_heal_pipeline_run",
    "tag_iteration_apply",
    "tag_iteration_suggest",
}

#: Tools whose result depends on the LLM gateway.
LLM_BACKED = {
    "auto_reject_pipeline_run",
    "compare_run",
    "contract_evaluate",
    "self_heal_pipeline_run",
    "tag_iteration_apply",
    "tag_iteration_suggest",
}

#: Irreversible deletion or in-place overwrite with no revision history.
DESTRUCTIVE = {
    "clause_delete",
    "clause_update",
    "criterion_delete",
    "criterion_update",
    "prompt_delete",
    "prompt_update",
    "rubric_delete",
    "rubric_update",
}


@pytest.fixture(scope="module")
def runtime() -> dict[str, dict]:
    """Each registered tool's hints as advertised over the protocol."""

    async def go():
        tools = await mcp.list_tools()
        out: dict[str, dict] = {}
        for t in tools:
            a = t.annotations
            assert a is not None, f"{t.name} declares no annotations"
            out[t.name] = {k: getattr(a, k) for k in HINTS}
        return out

    return asyncio.run(go())


def test_every_tool_declares_all_four_hints(runtime):
    assert runtime, "no tools registered"
    for name, hints in runtime.items():
        for k in HINTS:
            assert hints[k] is not None, f"{name}.{k} is undeclared"


def test_runtime_registry_matches_annotation_table(runtime):
    assert set(runtime) == set(TOOL_ANNOTATIONS), (
        "registry and annotation table disagree; register every new tool in "
        "annotations.TOOL_ANNOTATIONS"
    )


def test_runtime_hints_match_annotation_table(runtime):
    for name, hints in runtime.items():
        assert hints == TOOL_ANNOTATIONS[name], (
            f"{name}: runtime {hints} != table {TOOL_ANNOTATIONS[name]}"
        )


def test_tools_that_write_state_are_not_read_only(runtime):
    for name in WRITES_STATE:
        assert name in runtime, f"{name} vanished from the registry"
        assert runtime[name]["readOnlyHint"] is False, (
            f"{name} writes persistent state but is marked read-only"
        )
    # Exhaustive both ways: any tool the runtime calls non-read-only must be in
    # the hand-written expectation, so an unlisted new write tool is caught.
    flagged = {n for n, h in runtime.items() if h["readOnlyHint"] is False}
    assert flagged == WRITES_STATE, (
        f"write set drifted: extra={sorted(flagged - WRITES_STATE)} "
        f"missing={sorted(WRITES_STATE - flagged)}"
    )


def test_read_only_tools_are_idempotent(runtime):
    readers = set(runtime) - WRITES_STATE
    assert readers, "write set covers every tool; the expectation is wrong"
    for name in readers:
        assert runtime[name]["readOnlyHint"] is True, f"{name} is not marked read-only"
        assert runtime[name]["idempotentHint"] is True, (
            f"{name} is read-only but not idempotent"
        )


def test_destructive_hint_matches_the_deleting_and_overwriting_tools(runtime):
    flagged = {n for n, h in runtime.items() if h["destructiveHint"]}
    assert flagged == DESTRUCTIVE, (
        f"destructive set drifted: extra={sorted(flagged - DESTRUCTIVE)} "
        f"missing={sorted(DESTRUCTIVE - flagged)}"
    )


def test_llm_backed_tools_are_open_world(runtime):
    for name in LLM_BACKED:
        assert runtime[name]["openWorldHint"] is True, (
            f"{name} calls the LLM gateway but is marked closed-world"
        )
    for name in set(runtime) - LLM_BACKED - WRITES_STATE:
        assert runtime[name]["openWorldHint"] is False, (
            f"{name} is a pure DB/corpus read; marking it open-world tells "
            "clients the result is not reproducible"
        )


def test_manifest_carries_the_same_annotations():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    declared = manifest.get("tool_annotations")
    assert isinstance(declared, dict), "tool-surface.json has no tool_annotations"
    assert declared == TOOL_ANNOTATIONS, (
        "tool-surface.json tool_annotations drifted from annotations.TOOL_ANNOTATIONS"
    )


def test_unknown_tool_raises_instead_of_defaulting():
    with pytest.raises(KeyError):
        annotations_for("no_such_tool")


def test_annotations_are_copies():
    a = annotations_for("clause_list")
    a["readOnlyHint"] = False
    assert annotations_for("clause_list")["readOnlyHint"] is True
    assert annotations_for("clause_get")["readOnlyHint"] is True
