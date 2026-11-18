"""Sampling a chunk table whose title lives on its document row.

Measured 2026-11-11 against the real text library: a chunk table is
``id / domain / document_id / chunk_no / chunk_text / section_path / …`` — it has
**no** ``chunk_id`` and **no** ``title``. The default mapping therefore failed
with ``table 'corpus_chunks_gov' has no column(s) ['title', 'chunk_id']``, so the
whole vertical could not be sampled and its concept layer was structurally
unreachable. Two facts matter here:

- the title belongs to the *document*, and the source already declares where it
  lives (``ingest_rule.document {table, id, doc_ref, title}``) — join it;
- a missing title is acceptable, a missing text/id column is not.

These tests drive ``_sample_text_tables`` against a stub connection so the SQL
shape (join, NULL title) is pinned without a real external database.
"""

from __future__ import annotations

import pytest

from src.bench import extraction


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return None


class _Conn:
    """Stub psycopg connection: answers the column probe and the row query."""

    def __init__(self, columns, rows, sink):
        self._columns, self._rows, self._sink = columns, rows, sink

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._sink.append(sql)
        if "information_schema" in sql:
            return _Cur([(c,) for c in self._columns])
        return _Cur(self._rows)


def _run(monkeypatch, *, columns, rows, rule):
    import psycopg

    sql: list[str] = []
    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: _Conn(columns, rows, sql))
    from src.bench import libraries as libs

    monkeypatch.setattr(libs, "resolve_location", lambda lbl: {"dsn_env": "postgresql://x"})
    monkeypatch.setattr(libs, "list_sources", lambda conn, library_id: [
        {"source_key": "gov", "uri": "corpus_chunks_gov", "ingest_rule": rule}
    ])
    out = extraction._sample_text_tables(
        None, lib={"id": 2, "library_key": "text-library"},
        allowed={"gov"}, limit=5,
    )
    return out, sql


_CHUNK_COLUMNS = ["id", "domain", "document_id", "chunk_no", "chunk_text", "section_path"]

_DOC_RULE = {
    "columns": {"id": "id", "text": "chunk_text"},
    "document": {"table": "corpus_documents", "id": "id", "doc_ref": "document_id",
                 "title": "title", "text": "content"},
}


def test_the_title_comes_from_the_declared_document_table(monkeypatch):
    rows, sql = _run(monkeypatch, columns=_CHUNK_COLUMNS,
                     rows=[(438312, "正文", "矿业权登记管理暂行办法")], rule=_DOC_RULE)
    assert len(rows) == 1
    assert rows[0]["chunk_id"] == "438312"
    assert rows[0]["text"] == "正文"
    assert rows[0]["title"] == "矿业权登记管理暂行办法"
    assert any("LEFT JOIN corpus_documents" in s for s in sql), sql


def test_a_chunk_table_without_any_title_column_still_samples(monkeypatch):
    """No document declaration, no title: None is fine, the rows are not."""
    rule = {"columns": {"id": "id", "text": "chunk_text"}}
    rows, sql = _run(monkeypatch, columns=_CHUNK_COLUMNS,
                     rows=[(1, "正文一", None)], rule=rule)
    assert [r["chunk_id"] for r in rows] == ["1"]
    assert rows[0]["title"] is None
    assert not any("LEFT JOIN" in s for s in sql)


def test_a_missing_text_column_is_an_error_naming_it(monkeypatch):
    rule = {"columns": {"id": "id", "text": "nope"}}
    with pytest.raises(ValueError, match="nope"):
        _run(monkeypatch, columns=_CHUNK_COLUMNS, rows=[], rule=rule)


def test_a_missing_id_column_is_an_error_naming_it(monkeypatch):
    rule = {"columns": {"id": "chunk_id", "text": "chunk_text"}}
    with pytest.raises(ValueError, match="chunk_id"):
        _run(monkeypatch, columns=_CHUNK_COLUMNS, rows=[], rule=rule)


def test_an_unsafe_identifier_never_reaches_the_sql(monkeypatch):
    """The join table/columns are interpolated; anything odd must be skipped."""
    rule = {"columns": {"id": "id", "text": "chunk_text"},
            "document": {"table": "corpus_documents; drop table x", "id": "id",
                         "doc_ref": "document_id", "title": "title"}}
    rows, sql = _run(monkeypatch, columns=_CHUNK_COLUMNS, rows=[(1, "正文", None)], rule=rule)
    assert rows[0]["title"] is None
    assert not any("drop table" in s for s in sql)


# --- truncation must not look like "the corpus had nothing" ----------------- #


def test_a_length_truncated_answer_raises_instead_of_returning_empty(monkeypatch):
    """finish_reason=length with empty content is a budget failure, not an empty run.

    Measured 2026-11-11: a whole gov concept round reported
    「语料可能不含可抽内容」 while the model had actually spent all 1,500 tokens
    on reasoning and returned nothing. The cause has to be named.
    """
    import httpx

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"finish_reason": "length", "message": {"content": ""}}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 1500}},
            }

    monkeypatch.setenv("OPENAI_API_BASE", "https://example.invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("EVAL_MODEL", "openai/m")
    monkeypatch.delenv("EXTRACT_MAX_TOKENS", raising=False)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _Resp())

    with pytest.raises(extraction.ExtractionError, match="token 预算截断"):
        extraction.complete("prompt")


def test_an_empty_answer_with_a_normal_finish_stays_empty(monkeypatch):
    """A model that stops on its own and says nothing is a legitimate empty answer."""
    import httpx

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}

    monkeypatch.setenv("OPENAI_API_BASE", "https://example.invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("EVAL_MODEL", "openai/m")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _Resp())

    assert extraction.complete("prompt") == ""


def test_the_default_budget_is_one_a_real_call_fits_in(monkeypatch):
    """1,500 was measured to truncate; the default must not silently regress."""
    import httpx

    seen = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}

    def _post(url, **kw):
        seen.update(kw.get("json") or {})
        return _Resp()

    monkeypatch.setenv("OPENAI_API_BASE", "https://example.invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("EVAL_MODEL", "openai/m")
    monkeypatch.delenv("EXTRACT_MAX_TOKENS", raising=False)
    monkeypatch.setattr(httpx, "post", _post)
    extraction.complete("prompt")
    assert seen["max_tokens"] >= 4000, seen["max_tokens"]
