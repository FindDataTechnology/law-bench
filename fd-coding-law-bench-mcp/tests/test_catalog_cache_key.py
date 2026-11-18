"""``contract_type_catalog`` 的缓存不得跨「要不要计数」两种形状复用。

为什么这条值得单独立案：2026-11-10 的 MCP 注册表对账里记了一条「条款工具读空表」——
`contract_type_catalog` 66 个类型的 base/tagged/custom 计数**全 0**，据此判"读路径错位，
须另立单处理"。2026-11-12 现网复核发现计数本身是对的（41 个类型非零、合计 186，
与 `clause_list` 的 186 行逐条对得上），真正能复现"全 0"的是本文件钉的这个顺序：

1. 先有人用 `include_clause_counts=false` 调一次（不计数、便宜）；
2. 结果被写进**同一个** `_catalog_cache`；
3. 5 分钟内任何人用 `true` 再问，拿到的都是那份零计数副本。

即：**一次"我要便宜的"就把"我要真实计数"的答案污染成假零**。这类假零最危险的地方是
它长得跟"库里没有数据"一模一样——审计按它下了结论，人按结论去改本来没错的读路径。

本用例因此双向钉住：
- `false` 之后 `true` 必须拿到真实计数（假零回归锚点）；
- `true` 之后 `false` 不得返回计数（反向——也不能让便宜的读拿到昂贵形状）。

Hermetic：模板注册表与条款表都被替换成内存实现，不碰数据库。
"""

from __future__ import annotations

import asyncio

import pytest

from fd_coding_law_bench_mcp.tools import catalog as catalog_mod


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例从空缓存开始；否则用例之间会互相喂缓存。"""
    catalog_mod._catalog_cache.clear()
    yield
    catalog_mod._catalog_cache.clear()


@pytest.fixture
def fake_sources(monkeypatch):
    """两个外部依赖换掉：模板注册表 + 条款表。"""

    def list_contract_types():
        return [{"key": "demo", "zh": "示范合同"}]

    def get_template(key):
        return {"slots": [{"name": "a"}, {"name": "b"}]}

    # 条款表：每个 category 各有固定条数，便于断言"到底有没有去查库"
    counts = {"base": 2, "tagged": 3, "custom": 5}

    def list_clauses(contract_type=None, *, category=None, q=None, tags=None, db=None):
        n = counts.get(category, 0)
        return [{"id": i, "contract_type": contract_type, "category": category,
                 "section": "当事人", "body": "正文", "slot_instructions": [],
                 "law_refs": [], "tags": {}} for i in range(n)]

    import src.clauses.store as store
    import src.contracts.templates as templates

    monkeypatch.setattr(templates, "list_contract_types", list_contract_types)
    monkeypatch.setattr(templates, "get_template", get_template)
    monkeypatch.setattr(store, "list_clauses", list_clauses)
    return counts


def _totals(rows: list[dict]) -> tuple[int, int, int]:
    return (
        sum(r["total_base_clauses"] for r in rows),
        sum(r["total_tagged_clauses"] for r in rows),
        sum(r["total_custom_clauses"] for r in rows),
    )


def test_cheap_call_does_not_poison_the_counted_answer(fake_sources):
    """先问便宜的，再问计数的：必须拿到真实计数，不能是零。"""
    cheap = asyncio.run(catalog_mod.contract_type_catalog(include_clause_counts=False))
    assert _totals(cheap) == (0, 0, 0), "不计数时三个计数就该是 0"

    counted = asyncio.run(catalog_mod.contract_type_catalog(include_clause_counts=True))
    assert _totals(counted) == (2, 3, 5), (
        "已被 include_clause_counts=false 的缓存污染："
        f"计数读拿到 {_totals(counted)}，应为 (2, 3, 5)"
    )


def test_counted_call_does_not_leak_counts_into_the_cheap_answer(fake_sources):
    """反向也钉住：先计数、再问便宜的，便宜的不得返回计数。"""
    counted = asyncio.run(catalog_mod.contract_type_catalog(include_clause_counts=True))
    assert _totals(counted) == (2, 3, 5)

    cheap = asyncio.run(catalog_mod.contract_type_catalog(include_clause_counts=False))
    assert _totals(cheap) == (0, 0, 0), (
        "便宜的读拿到了计数形状：缓存按形状分了键吗？"
    )


def test_same_shape_still_cached(fake_sources):
    """分键之后同形状仍要命中缓存——否则每次调用都打库。"""
    import src.clauses.store as store

    calls = {"n": 0}
    real = store.list_clauses

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    store.list_clauses = counting  # type: ignore[assignment]
    try:
        asyncio.run(catalog_mod.contract_type_catalog(include_clause_counts=True))
        first = calls["n"]
        asyncio.run(catalog_mod.contract_type_catalog(include_clause_counts=True))
        assert calls["n"] == first, "同形状第二次调用不该再查库"
    finally:
        store.list_clauses = real  # type: ignore[assignment]
