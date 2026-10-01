"""CrewAI retrieval tool: the drafter grounds generation in retrieved precedent.

The tool is optional (``RAG_TOOL_ENABLED``) and degrades gracefully - on any
backend failure (Elasticsearch / OpenRouter / MinIO unreachable) it returns an
empty string so the drafter proceeds without retrieval, never propagating an
exception to the crew.
"""

from __future__ import annotations

from crewai.tools import BaseTool

from src.settings import RAG_TOOL_ENABLED

from .query import search


class ContractSearchTool(BaseTool):
    name: str = "contract_search"
    description: str = (
        "检索与起草需求相关的历史合同模板与已生成草案条款。"
        "输入：自然语言查询（中文或英文）。"
        "返回带来源路径的上下文片段；若无匹配则返回空字符串。"
        "Retrieve clauses from prior contract templates and generated drafts "
        "relevant to the drafting request. Input: a natural-language query. "
        "Returns formatted context chunks with their source path, or empty."
    )

    def _run(self, query: str) -> str:
        try:
            results = search(query, top_k=5)
        except Exception:
            return ""  # graceful degradation: no retrieval, drafter proceeds
        if not results:
            return ""
        return "\n\n".join(_format(r) for r in results)


def _format(r: dict) -> str:
    score = f" (score={r['score']:.3f})" if r.get("score") is not None else ""
    return f"[来源/source: {r['source_path']}{score}]\n{r['text']}"


def get_rag_tool():
    """Return the retrieval tool, or None when ``RAG_TOOL_ENABLED`` is off."""
    if not RAG_TOOL_ENABLED:
        return None
    return ContractSearchTool()
