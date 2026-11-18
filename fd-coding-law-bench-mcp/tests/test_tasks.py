"""长任务句柄（mcp-long-running-operations 组 5，law-bench 侧）。

law-bench 有两个长任务家族，各自已经持久化结果，但此前**没有统一的查询
入口**：调用方拿到 `pipeline_run_id` 或 `trace_id`，要自己知道该去哪张表查。
一个没有查询路径的句柄等于没有句柄。

本文件钉住的是**如实报告**这条纪律：

- pipeline：库里查到 = completed（含 progress 用判据通过数表达），查不到 =
  not_found；
- batch：`trace_id` 只是日志关联键、不落条目表，故报
  `unknown_not_persisted` **并说明后果**，而不是伪造一个 completed；
- 认不出家族的句柄 = not_found + 说明，不猜错表去查。

**为什么不伪造 running/interrupted**：那需要任务表记录提交时刻，batch 家族
目前没有。编一个中间态会让调用方对着假进度条干等——比"我查不到"更坏。
"""
from __future__ import annotations

import pytest

from fd_coding_law_bench_mcp.tasks import (
    COMPLETED, NOT_FOUND, failed_items_for, task_status,
)


# ── 句柄识别 ───────────────────────────────────────────────────

def test_numeric_handle_is_pipeline(monkeypatch):
    import fd_coding_law_bench_mcp.tasks as tasks

    monkeypatch.setattr(tasks, "_get_pipeline_run", lambda pid: None)
    assert task_status("42")["kind"] == "pipeline"


def test_trace_prefixed_handle_is_batch():
    assert task_status("trace-abc123")["kind"] == "batch"


@pytest.mark.parametrize("handle", ["", "   ", "whatever", "abc-123"])
def test_unrecognized_handle_is_reported_not_guessed(handle):
    """认不出就不要猜错表去查。"""
    out = task_status(handle)
    assert out["status"] == NOT_FOUND
    assert out["kind"] is None
    assert "家族" in out["error"]


# ── batch 家族：如实说明不可查 ────────────────────────────────

def test_batch_handle_reports_not_persisted_with_consequences():
    out = task_status("trace-abc123")
    assert out["kind"] == "batch"
    assert out["status"] == "unknown_not_persisted"
    # 关键是给出**该怎么做**，不只是说"查不到"
    assert "contract_generate_batch" in out["error"]


def test_batch_failed_items_is_empty_and_explained():
    """无法从句柄反推条目时返回空列表，不编造条目。"""
    assert failed_items_for("trace-abc123") == []


# ── pipeline 家族：查到即 completed ───────────────────────────

def test_pipeline_found_is_completed_with_progress(monkeypatch):
    import fd_coding_law_bench_mcp.tasks as tasks

    monkeypatch.setattr(tasks, "_get_pipeline_run", lambda pid: {
        "id": pid, "score": 8.0, "max_score": 10, "n_passed": 8,
        "n_criteria": 10, "all_pass": False, "iteration": 2,
        "eval_run_id": 7, "created_at": "2025-01-01T00:00:00",
    })
    out = task_status("42")
    assert out["found"] is True
    assert out["status"] == COMPLETED
    assert out["terminal"] is True
    assert out["progress"] == "8/10"
    assert out["counts"] == {"ok": 8, "failed": 2}
    assert out["result"]["iteration"] == 2


def test_pipeline_missing_is_not_found(monkeypatch):
    import fd_coding_law_bench_mcp.tasks as tasks

    monkeypatch.setattr(tasks, "_get_pipeline_run", lambda pid: None)
    out = task_status("42")
    assert out["found"] is False
    assert out["status"] == NOT_FOUND
    assert "pipeline_runs" in out["error"], "要说清是去哪张表查的"


def test_failed_items_empty_when_all_pass(monkeypatch):
    import fd_coding_law_bench_mcp.tasks as tasks

    monkeypatch.setattr(tasks, "_get_pipeline_run", lambda pid: {
        "id": pid, "all_pass": True, "iteration": 1, "n_passed": 5, "n_criteria": 5})
    assert failed_items_for("42") == []


def test_failed_items_names_the_iteration_when_not_passed(monkeypatch):
    """未全通过时给出 iteration：调用方据此判断该换 rubric 还是重跑。"""
    import fd_coding_law_bench_mcp.tasks as tasks

    monkeypatch.setattr(tasks, "_get_pipeline_run", lambda pid: {
        "id": pid, "all_pass": False, "iteration": 3, "n_passed": 2, "n_criteria": 6})
    out = failed_items_for("42")
    assert len(out) == 1
    assert "iteration=3" in out[0]
