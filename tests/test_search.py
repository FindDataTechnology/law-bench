"""Tests for the RAG search subsystem (hermetic: backends faked).

The LlamaIndex / Elasticsearch / OpenRouter / MinIO backends are faked by
monkeypatching at the function boundary (``src.search.query.search``,
``src.search.embeddings.get_embed_model``, ``src.search.rag_tool.search``) so
the suite needs no external services. The embedding-dimension guard and the
CrewAI tool's graceful degradation are exercised directly.
"""

from __future__ import annotations

import pytest

from src.settings import ConfigError, EMBEDDING_DIMS


# --- /api/search + /search page (query.search faked) ----------------------- #


def _fake_results(query="q", top_k=5):
    return [
        {"text": f"clause about {query}", "source_path": "contracts/templates/x.md", "score": 0.9},
        {"text": "another clause", "source_path": "contracts/drafts/y.md", "score": 0.5},
    ]


def test_search_api_returns_results(app_client, monkeypatch):
    monkeypatch.setattr("src.search.query.search", _fake_results)
    r = app_client.get("/api/search?q=保密义务")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["source_path"] == "contracts/templates/x.md"
    assert data[0]["score"] == 0.9


def test_search_api_empty_query_returns_empty(app_client):
    r = app_client.get("/api/search?q=")
    assert r.status_code == 200
    assert r.json() == []


def test_search_api_backend_error_returns_503(app_client, monkeypatch):
    def _boom(q, top_k=5):
        raise RuntimeError("es down")
    monkeypatch.setattr("src.search.query.search", _boom)
    r = app_client.get("/api/search?q=x")
    assert r.status_code == 503
    assert "es down" in r.json()["error"]


def test_search_page_renders_results(app_client, monkeypatch):
    monkeypatch.setattr("src.search.query.search", _fake_results)
    html = app_client.get("/search?q=保密义务").text
    assert "语义搜索" in html
    assert "contracts/templates/x.md" in html
    assert "clause about 保密义务" in html


def test_search_page_no_query(app_client):
    html = app_client.get("/search").text
    assert "语义搜索" in html
    assert "search-form" in html or 'name="q"' in html


# --- embedding dimension guard --------------------------------------------- #


class _FakeEmbed:
    def __init__(self, dims):
        self._dims = dims

    def get_text_embedding(self, _text):
        return [0.0] * self._dims


def test_verify_dimensions_passes_at_configured_dim(monkeypatch):
    from src.search import embeddings

    monkeypatch.setattr(embeddings, "get_embed_model", lambda: _FakeEmbed(EMBEDDING_DIMS))
    assert embeddings.verify_dimensions() == EMBEDDING_DIMS


def test_verify_dimensions_rejects_wrong_dim(monkeypatch):
    from src.search import embeddings

    monkeypatch.setattr(embeddings, "get_embed_model", lambda: _FakeEmbed(1024))
    with pytest.raises(ConfigError):
        embeddings.verify_dimensions()


# --- CrewAI RAG tool (rag_tool.search faked) ------------------------------- #


def test_rag_tool_returns_context(monkeypatch):
    from src.search import rag_tool

    monkeypatch.setattr(rag_tool, "search", _fake_results)
    tool = rag_tool.ContractSearchTool()
    out = tool._run("保密义务")
    assert "contracts/templates/x.md" in out
    assert "clause about 保密义务" in out


def test_rag_tool_empty_when_no_results(monkeypatch):
    from src.search import rag_tool

    monkeypatch.setattr(rag_tool, "search", lambda q, top_k=5: [])
    tool = rag_tool.ContractSearchTool()
    assert tool._run("anything") == ""


def test_rag_tool_degrades_gracefully_on_backend_failure(monkeypatch):
    from src.search import rag_tool

    def _boom(q, top_k=5):
        raise RuntimeError("openrouter down")
    monkeypatch.setattr(rag_tool, "search", _boom)
    tool = rag_tool.ContractSearchTool()
    # Must not raise - the drafter proceeds without retrieval.
    assert tool._run("anything") == ""
