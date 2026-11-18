"""generation_jobs 的僵尸清扫（审计 03 §10）。

`generation_jobs` 的终态只有后台任务自己在同一进程里写。滚动部署 / OOM /
pod 被驱逐 / SIGTERM 落在 202 与收尾之间时，行会永远停在 `pending` 或
`running`，而 `src/` 里没有任何启动清扫或 `updated_at` 超时。客户端轮询
`GET /api/generation-jobs/{id}` 会被告知「还在跑」，直到天荒地老。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.eval import store as eval_store  # noqa: E402


def test_stale_generation_jobs_are_reaped_at_startup(empty_db):
    """重启后遗留的 pending/running 任务必须被扫成 failed，不能永远挂着。

    审计 03 §10：`generation_jobs` 的终态只有后台任务自己在同一进程里写。
    滚动部署 / OOM / pod 被驱逐 / SIGTERM 落在 202 与收尾之间时，行就永远停在
    `pending` 或 `running`，而 `src/` 里没有任何启动清扫、reaper 或
    `updated_at` 超时。客户端轮询 `GET /api/generation-jobs/{id}` 会被告知
    「还在跑」，直到天荒地老。

    修法：启动时一次 `UPDATE ... SET status='failed', error_message='interrupted
    by restart'` 把非终态行收掉。本用例直接调那个清扫函数。
    """
    from src.eval import store as eval_store

    ensure = getattr(eval_store, "reap_stale_generation_jobs", None)
    assert ensure is not None, (
        "没有 reap_stale_generation_jobs —— 重启后 pending/running 行永远不终结"
    )

    eval_store.ensure_schema(db_path=empty_db)
    jid_p = eval_store.store_generation_job("pipeline", "labor", db_path=empty_db)
    jid_r = eval_store.store_generation_job("pipeline", "labor", db_path=empty_db)
    eval_store.update_generation_job(jid_r, status="running", db_path=empty_db)
    jid_done = eval_store.store_generation_job("pipeline", "labor", db_path=empty_db)
    eval_store.update_generation_job(jid_done, status="completed", db_path=empty_db)

    n = eval_store.reap_stale_generation_jobs(db_path=empty_db)
    assert n == 2, f"应扫掉 2 条非终态，实际 {n}"

    rows = {
        r["id"]: r
        for r in eval_store.list_generation_jobs(db_path=empty_db)
    }
    assert rows[jid_p]["status"] == "failed"
    assert rows[jid_r]["status"] == "failed"
    assert "interrupted" in (rows[jid_p].get("error_message") or "").lower()
    # 已完成的不能被改成 failed
    assert rows[jid_done]["status"] == "completed"
