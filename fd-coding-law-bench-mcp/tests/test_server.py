"""Server-level tests: the full tool set is registered, and ``__main__`` imports."""

from __future__ import annotations

import asyncio

EXPECTED_TOOLS = {
    "agent_run_get",
    "agent_run_list",
    "agent_run_store",
    "auto_reject_pipeline_run",
    "clause_delete",
    "clause_get",
    "clause_list",
    "clause_review",
    "clause_update",
    "compare_get",
    "compare_list",
    "compare_matrix",
    "compare_run",
    "contract_content",
    "contract_download",
    "contract_evaluate",
    "contract_generate",
    "contract_generate_batch",
    "contract_generate_stored",
    "contract_type_catalog",
    "criterion_add",
    "criterion_delete",
    "criterion_reorder",
    "criterion_update",
    "law_info",
    "law_references",
    "law_types",
    "pipeline_get",
    "pipeline_list",
    "prompt_create",
    "prompt_delete",
    "prompt_get",
    "prompt_list",
    "prompt_update",
    "rubric_create",
    "rubric_delete",
    "rubric_get",
    "rubric_list",
    "rubric_update",
    "run_draft",
    "run_get",
    "run_list",
    "search_clauses",
    "self_heal_pipeline_run",
    "tag_combinations_list",
    "tag_iteration_apply",
    "tag_iteration_suggest",
    "tag_validate",
    "tag_vocab_list",
    "type_metadata",
    "validation_check",
    "validation_list",
}


def test_main_module_importable():
    import fd_coding_law_bench_mcp.__main__ as main_mod

    assert hasattr(main_mod, "_entry")


def test_registers_all_tools():
    from fastmcp import Client

    from fd_coding_law_bench_mcp.server import mcp

    async def _list():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = asyncio.run(_list())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS, f"missing: {EXPECTED_TOOLS - names}; extra: {names - EXPECTED_TOOLS}"
