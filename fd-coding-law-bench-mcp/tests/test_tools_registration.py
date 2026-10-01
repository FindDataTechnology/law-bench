"""Registration smoke tests: the server advertises the full expected tool set,
every tool module imports without error, and each tool carries its concept tag.
"""

from __future__ import annotations

import asyncio

# The canonical, expected tool set. Any drift (a mis-named or unregistered
# ``@mcp.tool``, or a removed tool) fails this test.
EXPECTED_TOOLS = {
    # contracts (generation, evaluation, content/catalog/artifacts)
    "contract_generate",
    "contract_generate_batch",
    "contract_generate_stored",
    "contract_evaluate",
    "contract_content",
    "contract_download",
    "contract_type_catalog",
    "type_metadata",
    # clauses (CRUD + tag review)
    "clause_list",
    "clause_get",
    "clause_update",
    "clause_delete",
    "clause_review",
    # rubrics (rubric + criterion management)
    "rubric_list",
    "rubric_get",
    "rubric_create",
    "rubric_update",
    "rubric_delete",
    "criterion_add",
    "criterion_update",
    "criterion_delete",
    "criterion_reorder",
    # prompts
    "prompt_list",
    "prompt_get",
    "prompt_create",
    "prompt_update",
    "prompt_delete",
    # eval (compare orchestration + run reads)
    "compare_run",
    "compare_list",
    "compare_get",
    "compare_matrix",
    "run_list",
    "run_get",
    "run_draft",
    # pipeline (self-heal / auto-reject orchestration)
    "self_heal_pipeline_run",
    "auto_reject_pipeline_run",
    "pipeline_list",
    "pipeline_get",
    # search
    "search_clauses",
    # law (law-info + legal-references reads)
    "law_types",
    "law_info",
    "law_references",
    # tags (vocabulary, validation, retag iteration)
    "tag_vocab_list",
    "tag_validate",
    "tag_combinations_list",
    "tag_iteration_apply",
    "tag_iteration_suggest",
    # validations (legal hard-limit constraints)
    "validation_check",
    "validation_list",
    # agent metrics
    "agent_run_store",
    "agent_run_list",
    "agent_run_get",
}

# Each tool's concept group. Read from the registered tool component's
# ``tags`` (protocol-level ``meta`` no longer carries them on fastmcp 3.4).
EXPECTED_TAGS = {
    "contract_generate": "contracts",
    "contract_generate_batch": "contracts",
    "contract_generate_stored": "contracts",
    "contract_evaluate": "contracts",
    "contract_content": "contracts",
    "contract_download": "contracts",
    "contract_type_catalog": "contracts",
    "type_metadata": "contracts",
    "clause_list": "clauses",
    "clause_get": "clauses",
    "clause_update": "clauses",
    "clause_delete": "clauses",
    "clause_review": "clauses",
    "rubric_list": "rubrics",
    "rubric_get": "rubrics",
    "rubric_create": "rubrics",
    "rubric_update": "rubrics",
    "rubric_delete": "rubrics",
    "criterion_add": "rubrics",
    "criterion_update": "rubrics",
    "criterion_delete": "rubrics",
    "criterion_reorder": "rubrics",
    "prompt_list": "prompts",
    "prompt_get": "prompts",
    "prompt_create": "prompts",
    "prompt_update": "prompts",
    "prompt_delete": "prompts",
    "compare_run": "eval",
    "compare_list": "eval",
    "compare_get": "eval",
    "compare_matrix": "eval",
    "run_list": "eval",
    "run_get": "eval",
    "run_draft": "eval",
    "self_heal_pipeline_run": "pipeline",
    "auto_reject_pipeline_run": "pipeline",
    "pipeline_list": "pipeline",
    "pipeline_get": "pipeline",
    "search_clauses": "search",
    "law_types": "law",
    "law_info": "law",
    "law_references": "law",
    "tag_vocab_list": "tags",
    "tag_validate": "tags",
    "tag_combinations_list": "tags",
    "tag_iteration_apply": "pipeline",
    "tag_iteration_suggest": "pipeline",
    "validation_check": "validations",
    "validation_list": "validations",
    "agent_run_store": "metrics",
    "agent_run_list": "metrics",
    "agent_run_get": "metrics",
}

# Every tool module that registers ``@mcp.tool`` decorators on import.
_TOOL_MODULES = (
    "fd_coding_law_bench_mcp.tools.compare",
    "fd_coding_law_bench_mcp.tools.clauses",
    "fd_coding_law_bench_mcp.tools.evaluate",
    "fd_coding_law_bench_mcp.tools.generate",
    "fd_coding_law_bench_mcp.tools.law_info",
    "fd_coding_law_bench_mcp.tools.pipeline",
    "fd_coding_law_bench_mcp.tools.auto_pipeline",
    "fd_coding_law_bench_mcp.tools.tag_iteration",
    "fd_coding_law_bench_mcp.tools.prompts",
    "fd_coding_law_bench_mcp.tools.rag",
    "fd_coding_law_bench_mcp.tools.rubrics",
    "fd_coding_law_bench_mcp.tools.tags",
    "fd_coding_law_bench_mcp.tools.content",
    "fd_coding_law_bench_mcp.tools.batch",
    "fd_coding_law_bench_mcp.tools.catalog",
    "fd_coding_law_bench_mcp.tools.artifacts",
    "fd_coding_law_bench_mcp.tools.agent_metrics",
    "fd_coding_law_bench_mcp.tools.validation",
)


def _list_tools():
    from fastmcp import Client

    from fd_coding_law_bench_mcp.server import mcp

    async def _list():
        async with Client(mcp) as client:
            return await client.list_tools()

    return asyncio.run(_list())


def test_advertised_tools_match_expected_set():
    tools = _list_tools()
    names = {t.name for t in tools}
    missing = EXPECTED_TOOLS - names
    extra = names - EXPECTED_TOOLS
    assert not missing, f"missing tools: {sorted(missing)}"
    assert not extra, f"unexpected extra tools: {sorted(extra)}"


def test_each_tool_carries_its_concept_tag():
    from fd_coding_law_bench_mcp.server import mcp

    tools = {t.name: t for t in _list_tools()}
    assert set(tools) == EXPECTED_TOOLS

    async def _component_tags():
        return {
            name: sorted((await mcp.get_tool(name)).tags or [])
            for name in EXPECTED_TAGS
        }

    tags_by_name = asyncio.run(_component_tags())
    for name, concept in EXPECTED_TAGS.items():
        tags = tags_by_name[name]
        assert concept in tags, (
            f"{name} expected concept tag {concept!r}, got tags={tags!r}"
        )


def test_tool_modules_import_cleanly():
    import importlib

    for mod_name in _TOOL_MODULES:
        # A failure here means a tool module has an import-time error (e.g. a
        # bad ``from ..server import mcp`` or a stray top-level ``src.*`` import).
        assert importlib.import_module(mod_name) is not None
