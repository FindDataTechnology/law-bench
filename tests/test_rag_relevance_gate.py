"""检索要么给出**相关**上下文，要么诚实报「没检索到」——不许静默降级（审计 03 §11）。

`ContractSearchTool._run` 有两处沉默：

**(a) 没有相关性闸**：`query.search` 把每个节点的 score 带出来，但没有任何地方
用它过滤。于是 top-5 即使全部接近 0 分，也照样拼进起草上下文——模型被递上一堆
无关判例，而提示词说这是判例。

**(b) 没有失败信号**：ES 挂了、embedding 端点挂了、MinIO 挂了，`except Exception`
一律 `return ""`，起草照常进行。docstring 把这叫「graceful degradation」——**策略
是对的**，但实现里没有计数器、没有日志、eval run 上也没有字段。后果：一整周
「零检索起草」的合同，与整周「全量检索」的，在所有产物里**无法区分**。

本文件钉住两件事：
1. 低于阈值的片段不进入上下文；全都不达标时返回空且**留痕**（warning 日志 + 计数）。
2. 检索抛异常时返回空、**留痕**，而不是静默吞掉。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import src.search.rag_tool as rag  # noqa: E402


def _node(score, text="片段", path="doc.md"):
    return {"text": text, "source_path": path, "score": score}


def test_low_score_chunks_are_not_injected(monkeypatch):
    """全部低分 → 上下文里不许出现这些片段。"""
    monkeypatch.setattr(rag, "search", lambda q, top_k=5: [
        _node(0.01, "无关A"), _node(0.02, "无关B"),
    ])
    out = rag.ContractSearchTool()._run("某问题")
    assert "无关A" not in out and "无关B" not in out, (
        "接近 0 分的片段被注入起草上下文 —— 模型被递上无关判例却被告知是判例"
    )


def test_relevant_chunks_still_pass(monkeypatch):
    """高分片段必须照常通过——不能一刀切把检索关掉。"""
    monkeypatch.setattr(rag, "search", lambda q, top_k=5: [
        _node(0.88, "相关片段"),
    ])
    out = rag.ContractSearchTool()._run("某问题")
    assert "相关片段" in out


def test_mixed_scores_keep_only_the_relevant_ones(monkeypatch):
    """混合时只保留达标的那部分（不是全有全无）。"""
    monkeypatch.setattr(rag, "search", lambda q, top_k=5: [
        _node(0.90, "高分片段"), _node(0.02, "低分片段"),
    ])
    out = rag.ContractSearchTool()._run("某问题")
    assert "高分片段" in out
    assert "低分片段" not in out


def test_search_failure_is_logged_not_silent(monkeypatch, caplog):
    """检索抛异常必须留痕（否则整周无检索与整周全检索不可区分）。"""
    def boom(q, top_k=5):
        raise RuntimeError("elasticsearch down")

    monkeypatch.setattr(rag, "search", boom)
    with caplog.at_level(logging.WARNING):
        out = rag.ContractSearchTool()._run("某问题")
    assert out == ""  # 降级策略不变：起草照常进行
    assert any("retriev" in r.message.lower() or "检索" in r.message for r in caplog.records), (
        "检索失败被静默吞掉 —— 没有任何日志/计数，产物里无法区分「零检索」与「有检索」"
    )


def test_all_filtered_out_is_logged(monkeypatch, caplog):
    """全都低于阈值时也要留痕：那是「检索到了但都不相关」，同样是信息。"""
    monkeypatch.setattr(rag, "search", lambda q, top_k=5: [_node(0.01, "无关")])
    with caplog.at_level(logging.WARNING):
        rag.ContractSearchTool()._run("某问题")
    assert caplog.records, "全部低于阈值时完全静默 —— 与「没检索」不可区分"


def test_healthz_exposes_retrieval_counters():
    """/healthz 必须把检索失败/拒绝计数暴露出来——否则计数器也是死的。

    我第一版只加了 `retrieval_stats()` 却没有调用者，那和审计 §11 批评的
    「没有失败信号」是同一个病：计数器存在但没人读，等于不存在。

    **但不能因此改状态码**：/healthz 是 liveness/readiness 探针目标，一次 ES
    抖动要是让它非 200，k8s 会把本来健康的 pod 重启掉——那是把「降级」放大成
    「停机」。
    """
    from fastapi.testclient import TestClient

    import src.search.rag_tool as rag_mod
    from src.web.app import create_app

    rag_mod._retrieval_failures = 3
    rag_mod._retrieval_denied = 2
    try:
        client = TestClient(create_app())
        resp = client.get("/healthz")
        assert resp.status_code == 200, "探针状态码不许因检索计数变化"
        body = resp.json()
        assert body.get("status") == "ok"
        stats = body.get("retrieval") or {}
        assert stats.get("failures") == 3, f"/healthz 没暴露检索失败计数：{body}"
        assert stats.get("denied") == 2
    finally:
        rag_mod._retrieval_failures = 0
        rag_mod._retrieval_denied = 0
