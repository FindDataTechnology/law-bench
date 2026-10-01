"""CrewAI retrieval tool: grounds the drafter in the 法规库 corpus via law-api.

Gated by ``LAW_SEARCH_ENABLED`` + ``LAW_API_KEY`` (see ``client.enabled``).
Every failure inside ``search`` already degrades to ``[]`` (client contract),
so the tool returns an empty string and the drafter proceeds — identical to
``src.search.rag_tool.ContractSearchTool``.
"""

from __future__ import annotations

from crewai.tools import BaseTool

from src.law_api import client


class LawSearchTool(BaseTool):
    name: str = "law_search"
    description: str = (
        "检索中国法律法规原文片段（法规库语义检索），用于起草时引用现行有效的法律依据。"
        "输入：自然语言查询（中文），如'民法典 离婚后子女抚养费'。"
        "返回带法规名称、时效状态（law_status）和 law_id 的原文片段；若无匹配则返回空字符串。"
        "Retrieve statute excerpts from the law corpus for grounding citations; "
        "each hit carries the law title, its validity status, and law id. "
        "Input: a natural-language query. Returns empty when nothing matches."
    )

    def _run(self, query: str) -> str:
        if not client.enabled():
            return ""
        if not client.first_use_smoke():
            return ""  # degraded for this process after a failed smoke
        hits = client.search(query, top_k=5)
        if not hits:
            return ""
        return "\n\n".join(_format(h) for h in hits)


def _format(hit: dict) -> str:
    """One context chunk: title + status + law_id header, then the excerpt.

    law_status travels in the context so the drafter sees validity signals
    (有效 / 已修改 / 已废止) next to every statute it might cite.
    """
    meta = [f"法规/law: {hit.get('title') or '未知'}"]
    if hit.get("law_status"):
        meta.append(f"状态/status: {hit['law_status']}")
    if hit.get("law_id") is not None:
        meta.append(f"law_id={hit['law_id']}")
    text = (hit.get("chunk_text") or "").strip()
    return f"[{', '.join(meta)}]\n{text}"


def get_law_search_tool():
    """Return the tool, or None when the feature is disabled (drafting proceeds)."""
    if not client.enabled():
        return None
    return LawSearchTool()
