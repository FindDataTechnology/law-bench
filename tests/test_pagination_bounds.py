"""分页不能把用户给的数字变成"让 Postgres 取五千万行再 fetchall"。

`workbench_browse` 一次取 `offset + limit + 1` 行（多出的一行是 has-next 信号），
所以 `offset` 直接决定这次请求要物化多少行。旧实现 `offset: int = Query(0, ge=0)`
没有上界，`?offset=50000000` 就会让 Postgres 返回五千万行、`fetchall()` 全部进内存
——任何有 content:read 的域成员改一下 URL 就能打挂工作台 pod。

两层防护，本文件各钉一条：

* 路由层：`offset` 有 `le=10000`（超了直接 422，而不是偷偷截断）；
* 核边界：`list_knowledge_units` 把 `limit` 钳到 `MAX_LIST_UNITS`——所有调用方
  都从这一个口子过，而危险的是 `fetchall` 而不是 SQL 本身（值是参数化的）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.bench.store import MAX_LIST_UNITS, list_knowledge_units  # noqa: E402


class _RecordingConn:
    """只记录 execute 的入参，不连库。

    这里断言的是"钳制后的值进了 SQL 参数"，不是游标行为——所以假对象足够。
    真正验证行数上界需要真 PG（工作台测试都挂 `seeded_db`），本机没有。
    """

    def __init__(self):
        self.limit = None

    def execute(self, sql, params):
        self.limit = params[-1]
        return self

    def fetchall(self):
        return []


def _row_to_dict_marker():
    return None


def test_limit_is_clamped_at_the_kernel_boundary():
    """传入离谱的 limit，进 SQL 的必须是上限而不是原值。"""
    conn = _RecordingConn()
    list_knowledge_units(conn, limit=50_000_000)
    assert conn.limit == MAX_LIST_UNITS, f"进 SQL 的 limit 是 {conn.limit}，未被钳制"


def test_normal_limit_passes_through():
    """正常分页值不许被改动（别把 50 改成 20000 之外的东西）。"""
    conn = _RecordingConn()
    list_knowledge_units(conn, limit=51)
    assert conn.limit == 51


def test_non_positive_limit_is_raised_to_one():
    """0 / 负数不许变成 `LIMIT 0`（那会静默返回空页）。"""
    for bad in (0, -5):
        conn = _RecordingConn()
        list_knowledge_units(conn, limit=bad)
        assert conn.limit == 1


def test_route_caps_offset():
    """结构性断言：路由的 offset 必须带 le=，否则用户能传任意大值。

    HTTP 层的端到端验证要真 PG（`seeded_db` fixture 连库），本机无库，故用源码
    断言守住"上界还在"这件事——这和 `test_write_granularity` 里守"两处写点都传
    granularity"是同一手法。
    """
    src = (REPO / "src" / "web" / "routes" / "authoring.py").read_text(encoding="utf-8")
    assert "offset: int = Query(0, ge=0, le=" in src, (
        "workbench_browse 的 offset 又变成无上界了——`?offset=50000000` 会重新变成 OOM 路径"
    )


def test_max_list_units_is_above_a_page():
    """上界必须高于一页（路由取 offset+limit+1），否则分页会被钳制打坏。"""
    assert MAX_LIST_UNITS >= 1000, (
        f"MAX_LIST_UNITS={MAX_LIST_UNITS} 太小，正常的深分页会被截断"
    )
