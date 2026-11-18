"""Tests for ``search_clauses``.

Hermetic: the DB and ``src.search.library_index.search`` are monkeypatched, so no
network and no database. Pins the four-state contract
(knowledge-surface-integrity「读路径三态可判别」+ mcp-error-semantics):

- hits pass through as ``{text, source_path, score}``;
- a valid query with no match is a *successful empty list*;
- a domain with no corpus is ``no_corpus`` / not retryable (未接线);
- a backend failure is ``upstream_unavailable`` / retryable — never an empty list;
- an unknown domain never silently falls back to the default domain.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class _FakeConn:
    """Minimal stand-in for a psycopg connection (execute → one row, or none)."""

    def __init__(self, row):
        self._row = row

    def execute(self, sql, params=None):  # noqa: ARG002 - signature parity
        row = self._row

        class _Cur:
            def fetchone(self_inner):
                return row

        return _Cur()

    def close(self):
        return None


def _patch(monkeypatch, *, domain_row, search_impl):
    """Wire the tool to a fake connection + a fake library search."""
    import src.search.library_index as library_index

    monkeypatch.setattr(library_index, "search", search_impl)

    import src.eval.db as db_mod

    monkeypatch.setattr(db_mod, "connect", lambda db=None: _FakeConn(domain_row))


async def test_rag_returns_chunks(monkeypatch):
    _patch(
        monkeypatch,
        domain_row={"path": "legal"},
        search_impl=lambda conn, *, domain_path, query, top_k=5: [
            {"text": "c1", "source_path": "a.md", "score": 0.9}
        ],
    )
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("试用期期限", top_k=3)
    assert out == [{"text": "c1", "source_path": "a.md", "score": 0.9}]


async def test_rag_reports_upstream_unavailable_on_failure(monkeypatch):
    """A backend outage is NOT an empty result: it carries a machine-readable code."""

    def boom(conn, *, domain_path, query, top_k=5):
        raise RuntimeError("qdrant unreachable")

    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=boom)

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("anything")
    assert out != []
    assert out[0]["error"] == "upstream_unavailable"
    assert out[0]["retryable"] is True
    assert "text" not in out[0], "错误标记不是命中项，不得带 text 字段"


async def test_rag_empty_result_on_no_match(monkeypatch):
    """The other arm: valid query, no match -> successful empty list."""
    _patch(
        monkeypatch,
        domain_row={"path": "legal"},
        search_impl=lambda conn, *, domain_path, query, top_k=5: [],
    )
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    assert await search_clauses("nothing matches") == []


async def test_unknown_domain_is_no_corpus_and_does_not_fall_back(monkeypatch):
    """An unknown domain must not answer from the default domain."""
    calls: list[str] = []

    def spy(conn, *, domain_path, query, top_k=5):
        calls.append(domain_path)
        return [{"text": "from-legal", "source_path": "x.md", "score": 1.0}]

    _patch(monkeypatch, domain_row=None, search_impl=spy)

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", domain="nope")
    assert calls == [], "未知域不得触发任何检索（静默回落＝假命中）"
    assert out[0]["error"] == "no_corpus"
    assert out[0]["retryable"] is False
    assert "text" not in out[0]


async def test_not_subscribed_maps_to_no_corpus(monkeypatch):
    """A registered domain with no subscription is 未接线, not an upstream fault."""
    import src.search.library_index as library_index

    def not_subscribed(conn, *, domain_path, query, top_k=5):
        raise library_index.NotSubscribed("no subscription")

    _patch(monkeypatch, domain_row={"path": "empty-domain"}, search_impl=not_subscribed)

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", domain="empty-domain")
    assert out[0]["error"] == "no_corpus"
    assert out[0]["retryable"] is False


async def test_default_domain_matches_web_face(monkeypatch):
    """Both surfaces must search the same corpus when no domain is given."""
    from fd_coding_law_bench_mcp.tools.rag import DEFAULT_DOMAIN

    from src.web.routes.search import DEFAULT_DOMAIN as WEB_DEFAULT

    assert DEFAULT_DOMAIN == WEB_DEFAULT


async def test_blank_query_short_circuits(monkeypatch):
    """Empty query is a no-match, not a backend call."""
    calls: list[str] = []
    _patch(
        monkeypatch,
        domain_row={"path": "legal"},
        search_impl=lambda conn, *, domain_path, query, top_k=5: calls.append(query) or [],
    )
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    assert await search_clauses("   ") == []
    assert calls == []


# ---------------------------------------------------------------------------
# min_score（change mcp-clause-search-score-floor）
#
# The four-state contract promised "valid, no match -> []", but the retrieval
# layer has no score floor, so a vector search always returns top_k neighbours.
# These tests pin the *caller-controlled* way to reach that state — and that
# the default path stays byte-identical.
# ---------------------------------------------------------------------------

_HITS = [
    {"text": "high", "source_path": "hi.md", "score": 0.9},
    {"text": "mid", "source_path": "mid.md", "score": 0.5},
    {"text": "low", "source_path": "low.md", "score": -0.2},
]


def _search_returning(hits):
    return lambda conn, *, domain_path, query, top_k=5: list(hits)


async def test_no_min_score_returns_every_hit(monkeypatch):
    """默认不过滤：条数与顺序都与引入该参数前一致。"""
    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=_search_returning(_HITS))
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", top_k=3)
    assert [h["text"] for h in out] == ["high", "mid", "low"]


async def test_min_score_filters_below_floor(monkeypatch):
    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=_search_returning(_HITS))
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", min_score=0.5)
    assert [h["text"] for h in out] == ["high", "mid"]


async def test_min_score_above_everything_is_a_successful_empty_list(monkeypatch):
    """全部低于下限 → 成功空集（不是 no_corpus、也不是 upstream_unavailable）。"""
    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=_search_returning(_HITS))
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", min_score=0.99)
    assert out == []


async def test_min_score_zero_is_a_real_floor_not_a_falsy_noop(monkeypatch):
    """0.0 必须当真下限：负分被滤掉。写成 `min_score or 0` 会让这条红。"""
    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=_search_returning(_HITS))
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", min_score=0.0)
    assert [h["text"] for h in out] == ["high", "mid"]


async def test_min_score_drops_hits_without_a_score(monkeypatch):
    """后端没回分数 = 无法证明达标，按不达标处理（不能混进结果）。"""
    hits = [{"text": "noscore", "source_path": "x.md", "score": None},
            {"text": "ok", "source_path": "y.md", "score": 0.4}]
    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=_search_returning(hits))
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", min_score=0.1)
    assert [h["text"] for h in out] == ["ok"]


async def test_min_score_never_filters_error_markers(monkeypatch):
    """错误标记不是命中项：给了下限也必须原样返回，否则空集会被误读成「无匹配」。"""
    _patch(monkeypatch, domain_row=None, search_impl=_search_returning(_HITS))
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("违约金", domain="nope", min_score=0.99)
    assert out[0]["error"] == "no_corpus"
    assert out[0]["retryable"] is False


async def test_rag_docstring_states_scores_are_backend_scoped():
    """分数只在同一后端内可比——这句话必须在 docstring 里（客户端读得到的地方）。"""
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    doc = search_clauses.__doc__ or ""
    assert "same backend" in doc
    assert "no default threshold" in doc.lower() or "deliberately no default" in doc.lower()


# ---------------------------------------------------------------------------
# 每调用一行遥测（change mcp-clause-search-call-telemetry）
# ---------------------------------------------------------------------------

import json as _json


def _capture(capsys):
    out = capsys.readouterr()
    lines = [l for l in (out.err + out.out).splitlines() if '"event": "search_clauses"' in l]
    return [_json.loads(l) for l in lines]


async def test_telemetry_emits_one_line_per_call_with_outcome(monkeypatch, capsys):
    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=_search_returning(_HITS))
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    await search_clauses("违约金", top_k=3)
    rec = _capture(capsys)
    assert len(rec) == 1
    assert rec[0]["outcome"] == "hit" and rec[0]["n"] == 3
    assert rec[0]["domain"] == "legal" and rec[0]["top_k"] == 3
    assert rec[0]["min_score"] is None and isinstance(rec[0]["elapsed_ms"], int)


async def test_telemetry_distinguishes_empty_and_no_corpus(monkeypatch, capsys):
    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=lambda conn, *, domain_path, query, top_k=5: [])
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    await search_clauses("违约金")
    _patch(monkeypatch, domain_row=None, search_impl=lambda conn, *, domain_path, query, top_k=5: [])
    await search_clauses("违约金", domain="nope")

    outcomes = [r["outcome"] for r in _capture(capsys)]
    assert outcomes == ["empty", "no_corpus"], outcomes


async def test_telemetry_marks_upstream_unavailable(monkeypatch, capsys):
    def boom(conn, *, domain_path, query, top_k=5):
        raise RuntimeError("qdrant unreachable")

    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=boom)
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    await search_clauses("违约金")
    rec = _capture(capsys)
    assert rec[0]["outcome"] == "upstream_unavailable"
    assert rec[0]["n"] == 1


async def test_telemetry_never_logs_the_query_text(monkeypatch, capsys):
    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=_search_returning(_HITS))
    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    marker = "ZZ_UNIQUE_QUERY_MARKER_9137"
    await search_clauses(marker)
    out = capsys.readouterr()
    assert marker not in (out.err + out.out)


async def test_telemetry_failure_does_not_change_the_result(monkeypatch):
    """遥测写失败（stderr 不可写）也不得影响返回。"""
    _patch(monkeypatch, domain_row={"path": "legal"}, search_impl=_search_returning(_HITS))
    import sys as _sys

    import fd_coding_law_bench_mcp.tools.rag as rag_mod

    class BoomStream:
        def write(self, _s):
            raise RuntimeError("stderr exploded")

        def flush(self):
            raise RuntimeError("stderr exploded")

    original = _sys.stderr
    _sys.stderr = BoomStream()
    try:
        out = await rag_mod.search_clauses("违约金", top_k=3)
    finally:
        _sys.stderr = original
    assert [h["text"] for h in out] == ["high", "mid", "low"]


def test_telemetry_does_not_depend_on_logging_configuration():
    """本进程 root 无 handler、默认 WARNING；遥测不得依赖 logging 配置。"""
    import inspect

    import fd_coding_law_bench_mcp.tools.rag as rag_mod

    src = inspect.getsource(rag_mod._emit_telemetry)
    assert "sys.stderr" in src, "必须直写当前 sys.stderr"
    assert "logging" not in src, "不得依赖 logging（root 无 handler 时 INFO 会被丢弃）"
