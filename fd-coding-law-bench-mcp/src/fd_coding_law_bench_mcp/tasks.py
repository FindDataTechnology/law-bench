"""长任务句柄的统一查询（mcp-long-running-operations 组 5）。

law-bench 有两个长任务家族，各自已经持久化了运行结果：

- **pipeline**（`self_heal_pipeline_run`）→ `pipeline_runs` 表，返回
  `pipeline_run_id`
- **batch**（`contract_generate_batch`）→ 返回 `trace_id`

但此前**没有统一的查询入口**：调用方拿到一个 id，要自己知道该去哪张表查、
用哪个函数。而 spec 要求"任务句柄可查询状态与结果"——一个句柄若没有对应的
查询路径，就等于没有句柄。

本模块提供两件事：

1. `task_status`：按句柄前缀认出是哪个家族，返回统一形状
   `{handle, kind, found, status, progress, counts, terminal}`。
2. `failed_items_for`：取出失败/未完成的条目，供分项重试使用。

**为什么不把两个家族改成同一张表**：它们已经各自落地（`pipeline_runs`
有 score/iteration/actions_taken；batch 的 trace_id 是日志关联键，本身不
落条目表）。统一形状在**查询层**做，而不是迁移既有表——改表会让已发布的
消费方和历史数据同时失效。

**状态语义**：两个家族都是"跑完即落库"，所以库里查到就是 `completed`；
查不到就是 `not_found`（从未提交）。这里**不**伪造 running/interrupted——
那需要任务表记录提交时刻，batch 家族目前没有。如实报告"本家族只能给出
completed / not_found"比给出一个编造的中间态更可取，后者会让调用方对着
一个假的进度条干等。
"""
from __future__ import annotations

from typing import Any, Optional

COMPLETED = "completed"
NOT_FOUND = "not_found"


def _kind_of(handle: str) -> Optional[str]:
    """按句柄形态认出家族。

    pipeline_run_id 是整数 id；batch 的 trace_id 形如 `trace-<hash>`。
    认不出就返回 None——宁可报"不认识这个句柄"，也不要猜错家族去查错表。
    """
    handle = (handle or "").strip()
    if not handle:
        return None
    if handle.isdigit():
        return "pipeline"
    if handle.startswith("trace-"):
        return "batch"
    return None


def task_status(handle: str) -> dict[str, Any]:
    """统一形状的任务状态查询。"""
    kind = _kind_of(handle)
    if kind is None:
        return {
            "handle": handle,
            "kind": None,
            "found": False,
            "status": NOT_FOUND,
            "error": "认不出该句柄属于哪个任务家族（pipeline 用数字 id，"
                     "batch 用 trace- 前缀）",
        }

    if kind == "pipeline":
        return _pipeline_status(int(handle))
    return _batch_status(handle)


def _pipeline_status(pipeline_id: int) -> dict[str, Any]:
    row = _get_pipeline_run(pipeline_id)
    base = {"handle": str(pipeline_id), "kind": "pipeline"}
    if row is None:
        return {**base, "found": False, "status": NOT_FOUND,
                "error": f"pipeline_runs 中没有 id={pipeline_id}"}
    n_passed = row.get("n_passed") or 0
    n_criteria = row.get("n_criteria") or 0
    return {
        **base,
        "found": True,
        "status": COMPLETED,
        "terminal": True,
        # 进度以"通过的判据数/判据总数"表达：这是流水线推进的真实度量，
        # 比编一个"处理了几条"更有意义（一次 run 只产一份合同）。
        "progress": f"{n_passed}/{n_criteria}",
        "counts": {"ok": n_passed, "failed": max(0, n_criteria - n_passed)},
        "result": {
            "score": row.get("score"),
            "max_score": row.get("max_score"),
            "all_pass": row.get("all_pass"),
            "iteration": row.get("iteration"),
            "eval_run_id": row.get("eval_run_id"),
            "created_at": row.get("created_at"),
        },
    }


#: 存储访问做成模块级可替换点：没有 DB 的环境（离线测试）要能测查询逻辑本身，
#: 而不是被迫先起一个 PostgreSQL。
def _get_pipeline_run(pipeline_id: int) -> Optional[dict]:
    from src.eval.pipeline_store import get_pipeline_run

    return get_pipeline_run(pipeline_id)


def _batch_status(trace_id: str) -> dict[str, Any]:
    """batch 家族：trace_id 是日志关联键，不落条目表。

    如实说明这一点，而不是返回一个假的 completed——调用方需要知道"这个家族
    的逐条结果只在调用的返回里，查询入口拿不到"。
    """
    return {
        "handle": trace_id,
        "kind": "batch",
        "found": None,  # 未知而非真假：没有条目表可查
        "status": "unknown_not_persisted",
        "error": "batch 家族目前只在调用返回里给出逐条结果（trace_id 是日志"
                 "关联键，不落条目表）。要分项重跑，请用调用返回里的失败"
                 "条目重新提交一次 contract_generate_batch。",
    }


def failed_items_for(handle: str) -> list[str]:
    """待重试的条目 key。

    pipeline 家族返回未通过的判据名（若存储里有）；batch 家族无法得出，
    如实返回空列表并由调用方按上面的 error 处理。
    """
    kind = _kind_of(handle)
    if kind != "pipeline":
        return []
    row = _get_pipeline_run(int(handle))
    if row is None:
        return []
    # actions_taken 记录了本轮做了什么；未通过的判据由 all_pass 表达，
    # 逐判据明细在 eval_runs 里——这里不展开，避免把两个表拼成一个假结构。
    return [] if row.get("all_pass") else [f"判据未全通过（iteration={row.get('iteration')}）"]
