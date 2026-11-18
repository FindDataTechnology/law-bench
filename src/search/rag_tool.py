"""CrewAI retrieval tool: the drafter grounds generation in retrieved precedent.

The tool is optional (``RAG_TOOL_ENABLED``) and degrades gracefully - on any
backend failure (Elasticsearch / OpenRouter / MinIO unreachable) it returns an
empty string so the drafter proceeds without retrieval, never propagating an
exception to the crew.

**但「优雅降级」不等于「静默降级」**（审计 03 §11）。本模块原来有两处沉默：

(a) 没有任何**相关性闸**：`query.search` 把每个节点的 score 带出来，却没有地方
    用它过滤。top-5 就算全部接近 0 分也照样拼进上下文——模型被递上一堆无关判例，
    而提示词说这是判例。
(b) 没有**失败信号**：异常一律 `return ""`，没有日志、没有计数、eval run 上也没有
    字段。于是一整周「零检索起草」的合同，与整周「全量检索」的，在所有产物里
    无法区分。

现在两条都有痕：低于 `_MIN_RELEVANCE_SCORE` 的片段被丢弃；检索异常、以及
「检索到了但全都不达标」都会打 warning 并计入 `_retrieval_failures` / 
`_retrieval_denied` 两个模块级计数器（进程内，供健康检查/日志读）。
"""

from __future__ import annotations

import logging

from crewai.tools import BaseTool

from src.settings import RAG_TOOL_ENABLED

from .query import search

logger = logging.getLogger(__name__)

#: 相关性下限。低于它的片段不进上下文——「宁可少给，也别把无关判例当判例」。
#: 0.35 是保守起点：llama-index 的 similarity 分数对真正相关的段落通常在 0.5+，
#: 而完全不相关的多在 0.2 以下。要调就调这一个常量。
_MIN_RELEVANCE_SCORE = 0.35

#: 进程内计数：检索失败次数 / 全部低于阈值次数。健康检查或日志可读它们，
#: 让「零检索窗口」在产物里留下痕迹，而不是消失得无影无踪。
_retrieval_failures = 0
_retrieval_denied = 0


def retrieval_stats() -> dict[str, int]:
    """当前进程的检索失败/拒绝计数（供健康检查与日志使用）。"""
    return {"failures": _retrieval_failures, "denied": _retrieval_denied}


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
        global _retrieval_failures, _retrieval_denied
        try:
            results = search(query, top_k=5)
        except Exception as exc:  # noqa: BLE001 - 降级策略不变，但必须留痕
            _retrieval_failures += 1
            logger.warning(
                "retrieval failed (%s: %s) — drafting proceeds ungrounded",
                type(exc).__name__, exc,
            )
            return ""
        if not results:
            return ""
        kept = [r for r in results if _is_relevant(r)]
        if not kept:
            _retrieval_denied += 1
            logger.warning(
                "retrieval returned %s chunk(s) but none above the relevance floor "
                "(%.2f); drafting proceeds ungrounded",
                len(results), _MIN_RELEVANCE_SCORE,
            )
            return ""
        return "\n\n".join(_format(r) for r in kept)


def _is_relevant(r: dict) -> bool:
    """片段是否达到相关性下限。

    score 缺失时**放行**（不因为拿不到分数就把检索关掉——那是另一种沉默：
    把「无法判断」当成「不相关」）。只有明确低于阈值才丢。
    """
    score = r.get("score")
    if score is None:
        return True
    try:
        return float(score) >= _MIN_RELEVANCE_SCORE
    except (TypeError, ValueError):
        return True


def _format(r: dict) -> str:
    score = f" (score={r['score']:.3f})" if r.get("score") is not None else ""
    return f"[来源/source: {r['source_path']}{score}]\n{r['text']}"


def get_rag_tool():
    """Return the retrieval tool, or None when ``RAG_TOOL_ENABLED`` is off."""
    if not RAG_TOOL_ENABLED:
        return None
    return ContractSearchTool()
