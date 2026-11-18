"""External library backends: Qdrant and a foreign pgvector table (§2).

Two claims are pinned here, both of which fail silently in production if wrong:

- **the source filter is the access control.** An external library holds hundreds
  of thousands of chunks that were never ingested by a domain, so there is no
  ``scope_path`` to filter on. A subscriber must see exactly the sources its
  ancestor chain granted — not one more.
- **the query is embedded by the library's own model.** Two 1024-dim spaces exist
  in this fleet (Qwen3-0.6B in Qdrant, Qwen3-8B in ``fd_text``), and a mismatch
  degrades similarity without raising. The embedder router is asserted on the
  request it actually sends, including the MRL ``dimensions`` field.

Nothing here talks to the network: the Qdrant adapter is exercised through an
httpx ``MockTransport`` and the pgvector adapter through a recording fake, so the
tests state the protocol rather than the deployment's current hostnames.
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.bench import libraries
from src.search import embedders, library_index
from src.settings import ConfigError


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.bench import templates
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    templates.create_template(
        conn=empty_db,
        name="tpl",
        created_by="t",
        schema={
            "entity_types": ["clause"],
            "concept_structures": {"clause": ["id"]},
            "relationship_kinds": ["cites_law"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": ["external"]},
        },
    )
    empty_db.execute(
        "INSERT INTO domains (key, name, template_id, template_version, created_by, path) "
        "SELECT 'legal','法律域',id,1,'t','legal' FROM ontology_templates ORDER BY id LIMIT 1"
    )
    empty_db.commit()
    return empty_db


@pytest.fixture(autouse=True)
def _clear_embedder_cache():
    embedders.clear_cache()
    yield
    embedders.clear_cache()


def _qdrant_library(conn, *, sources: dict[str, dict], name="law-library") -> dict:
    lib = libraries.create_library(
        conn, library_key=name, name=name, created_by="t", backend="qdrant",
        embedding_model="Qwen/Qwen3-Embedding-0.6B", dims=1024,
        location={"url_env": "TEST_QDRANT_URL", "collection": "law_chunks_v2"},
    )
    for key, rule in sources.items():
        libraries.add_source(
            conn, library_key=name, source_key=key, uri=f"collection:law_chunks_v2/{key}",
            created_by="t", source_kind="external-filter", ingest_rule=rule,
        )
    return lib


class _Stub:
    """Records requests and answers from a callable — the HTTP seam under test."""

    def __init__(self, answer):
        self.calls: list[dict] = []
        self._answer = answer

    def __call__(self, url, *, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "body": json, "headers": headers})
        payload = self._answer(url, json)
        if isinstance(payload, Exception):
            raise payload
        # `request=` is required: `raise_for_status()` reads response.request.
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


def _domain(conn, key="legal") -> dict:
    return dict(conn.execute("SELECT * FROM domains WHERE key=%s", (key,)).fetchone())


# ── storage contract ─────────────────────────────────────────────────────────


def test_external_library_requires_an_env_named_location(conn):
    with pytest.raises(ValueError, match="url_env"):
        libraries.create_library(
            conn, library_key="bad", name="bad", created_by="t", backend="qdrant"
        )
    with pytest.raises(ValueError, match="collection"):
        libraries.create_library(
            conn, library_key="bad2", name="bad2", created_by="t", backend="qdrant",
            location={"url_env": "QDRANT_URL"},
        )


def test_location_never_stores_a_value_only_a_name(conn):
    """A DSN in the database would leak through dumps, pages and commits."""
    lib = _qdrant_library(conn, sources={"statutes": {"match": {"category": "行政法规"}}})
    loc = lib["location"] if isinstance(lib["location"], dict) else json.loads(lib["location"])
    assert loc["url_env"] == "TEST_QDRANT_URL"
    assert ":" not in loc["url_env"] and "/" not in loc["url_env"]


def test_resolve_location_names_the_missing_variable(conn, monkeypatch):
    lib = _qdrant_library(conn, sources={"statutes": {"match": {"category": "行政法规"}}})
    monkeypatch.delenv("TEST_QDRANT_URL", raising=False)
    with pytest.raises(ValueError, match="TEST_QDRANT_URL"):
        libraries.resolve_location(lib)
    monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")
    assert libraries.resolve_location(lib)["url_env"] == "http://qdrant.test:6333"


# ── filter translation ───────────────────────────────────────────────────────


def test_source_filter_or_ed_across_granted_sources(conn):
    _qdrant_library(
        conn,
        sources={
            "admin": {"match": {"category": "行政法规"}},
            "judicial": {"match": {"category": "司法解释"}},
            "local": {"match": {"category": "地方性法规"}},
        },
    )
    lib = libraries.get_library(conn, library_key="law-library")
    srcs = libraries.list_sources(conn, library_id=lib["id"])
    filt = library_index.qdrant_filter(srcs, {"admin", "judicial"})
    assert "should" in filt and len(filt["should"]) == 2
    got = {b["must"][0]["match"]["value"] for b in filt["should"]}
    assert got == {"行政法规", "司法解释"}  # the ungranted source is absent


def test_a_source_may_cover_several_spellings_of_one_class(conn):
    """地方性法规 / 地方法规 are the same class spelled two ways (166,428 points):
    a source that names only one of them silently drops half the corpus."""
    _qdrant_library(
        conn,
        sources={"local": {"match": {"category": ["地方性法规", "地方法规"]}}},
    )
    lib = libraries.get_library(conn, library_key="law-library")
    srcs = libraries.list_sources(conn, library_id=lib["id"])
    filt = library_index.qdrant_filter(srcs, {"local"})
    assert filt["must"][0]["match"] == {"any": ["地方性法规", "地方法规"]}


def test_empty_grant_is_unrestricted_not_empty(conn):
    """`allowed=set()` means "no narrowing" everywhere else in this module.

    Reading it as "nothing granted" made the whole-library count report 0 while
    the per-source counts summed to the full collection — the two cannot both be
    true, and the library page showed the wrong one.
    """
    _qdrant_library(conn, sources={"admin": {"match": {"category": "行政法规"}}})
    lib = libraries.get_library(conn, library_key="law-library")
    srcs = libraries.list_sources(conn, library_id=lib["id"])
    assert library_index.qdrant_filter(srcs, set()) is None


def test_ungranted_source_cannot_smuggle_a_whole_collection(conn):
    """A rule-less source means 'whole collection'; granting nothing must not
    inherit that."""
    _qdrant_library(conn, sources={"everything": {}})
    lib = libraries.get_library(conn, library_key="law-library")
    srcs = libraries.list_sources(conn, library_id=lib["id"])
    filt = library_index.qdrant_filter(srcs, {"some-other-source"})
    assert filt != None  # an impossible filter, never "no filter"
    assert filt["must"][0]["match"]["value"] == "__none__"


# ── Qdrant search ────────────────────────────────────────────────────────────


def test_qdrant_search_sends_the_filter_and_maps_hits(conn, monkeypatch):
    _qdrant_library(
        conn,
        sources={
            "admin": {"match": {"category": "行政法规"}},
            "judicial": {"match": {"category": "司法解释"}},
        },
    )
    dom = _domain(conn)
    libraries.subscribe(conn, domain_id=dom["id"], library_key="law-library",
                        created_by="t", source_filter=["admin"])

    stub = _Stub(lambda url, body: {"result": [
        {"id": 7, "score": 0.91,
         "payload": {"chunk_text": "行政法规正文", "title": "某条例", "chunk_no": 3,
                     "category": "行政法规"}},
        {"id": 9, "score": 0.42,
         "payload": {"chunk_text": "司法解释正文", "title": "某解释", "chunk_no": 1,
                     "category": "司法解释"}},
    ]})

    monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")
    monkeypatch.setattr(library_index, "_http_post", stub)
    # Provide a query vector without touching an embedding service.
    hits = library_index.search(
        conn, domain_path=dom["path"], query="条例", embed=lambda texts: [[0.1] * 1024],
        top_k=2,
    )

    assert "/collections/law_chunks_v2/points/search" in stub.calls[0]["url"]
    body = stub.calls[0]["body"]
    assert body["filter"] == {"must": [{"key": "category", "match": {"value": "行政法规"}}]}
    assert len(body["vector"]) == 1024
    assert [h["text"] for h in hits] == ["行政法规正文", "司法解释正文"]
    assert hits[0]["source_path"] == "某条例#3"
    assert hits[0]["library_key"] == "law-library"
    # score order preserved, and the grant decided which source each hit is
    # attributed to — computed from the payload, not concatenated by guesswork.
    assert hits[0]["score"] == 0.91 and hits[1]["score"] == 0.42
    assert hits[0]["source_key"] == "admin" and hits[1]["source_key"] == "judicial"


def test_count_scope_counts_the_remote_store(conn, monkeypatch):
    _qdrant_library(conn, sources={"admin": {"match": {"category": "行政法规"}}})
    dom = _domain(conn)
    libraries.subscribe(conn, domain_id=dom["id"], library_key="law-library", created_by="t")
    monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")

    stub = _Stub(lambda url, body: {"result": {"count": 614}})
    monkeypatch.setattr(library_index, "_http_post", stub)
    counted = library_index.count_scope(conn, domain_path=dom["path"])
    assert "/points/count" in stub.calls[0]["url"]
    assert counted["chunks"] == 614  # not zero: the vectors are not local


def test_unreachable_store_reports_an_error_instead_of_zero(conn, monkeypatch):
    _qdrant_library(conn, sources={"admin": {"match": {"category": "行政法规"}}})
    dom = _domain(conn)
    libraries.subscribe(conn, domain_id=dom["id"], library_key="law-library", created_by="t")
    monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")

    monkeypatch.setattr(
        library_index, "_http_post",
        _Stub(lambda url, body: RuntimeError("connection refused")),
    )
    counted = library_index.count_scope(conn, domain_path=dom["path"])
    assert counted["chunks"] == 0
    assert counted["errors"] and "connection refused" in counted["errors"][0]


# ── embedder routing ─────────────────────────────────────────────────────────


def test_two_1024_spaces_are_not_interchangeable():
    local = embedders.embedder_for("Qwen/Qwen3-Embedding-0.6B", 1024)
    gateway = embedders.embedder_for("Qwen/Qwen3-Embedding-8B", 1024)
    assert local.space != gateway.space
    assert local.dims == gateway.dims == 1024


def test_mrl_model_requests_explicit_dimensions(monkeypatch):
    """Without `dimensions` the 8B model answers in 4096 dims — another space."""
    monkeypatch.setenv(embedders.GATEWAY_KEY_ENV, "test-key")
    stub = _Stub(lambda url, body: {"data": [{"embedding": [0.5] * 1024}]})
    monkeypatch.setattr(embedders, "_http_post", stub)
    emb = embedders.embedder_for("Qwen/Qwen3-Embedding-8B", 1024)
    emb(["probe"])
    assert stub.calls[0]["body"]["dimensions"] == 1024
    assert stub.calls[0]["body"]["model"] == "Qwen/Qwen3-Embedding-8B"


def test_wrong_dimensions_raise_instead_of_degrading(monkeypatch):
    monkeypatch.setenv(embedders.GATEWAY_KEY_ENV, "test-key")
    monkeypatch.setattr(
        embedders, "_http_post",
        _Stub(lambda url, body: {"data": [{"embedding": [0.1] * 4096}]}),
    )
    emb = embedders.embedder_for("Qwen/Qwen3-Embedding-8B", 1024)
    with pytest.raises(ConfigError, match="4096"):
        emb(["probe"])


def test_local_model_calls_the_in_cluster_contract(monkeypatch):
    monkeypatch.setenv(embedders.LOCAL_EMBED_URL_ENV, "http://embed.test:6100")
    stub = _Stub(lambda url, body: {"embeddings": [[0.2] * 1024]})
    monkeypatch.setattr(embedders, "_http_post", stub)
    emb = embedders.embedder_for("Qwen/Qwen3-Embedding-0.6B", 1024)
    out = emb(["第一条"])
    assert stub.calls[0]["url"] == "http://embed.test:6100/embed"
    assert stub.calls[0]["body"] == {"input": ["第一条"]}
    assert len(out[0]) == 1024


def test_text_only_library_is_skipped_by_search_not_fatal(conn, monkeypatch):
    """A text-table library holds no vectors.

    Measured 2026-11-09: registering the guide cases as a text table with
    `dims=1` made *every* search in that domain fail on embedder resolution —
    one line's extraction-only library took another line's retrieval down with it.
    """
    lib = libraries.create_library(
        conn, library_key="cases", name="cases", created_by="t",
        backend="pgvector-external", dims=1, location={"dsn_env": "X"},
    )
    libraries.add_source(conn, library_key="cases", source_key="guide_cases",
                         uri="guide_cases", created_by="t", source_kind="text-table")
    legal = conn.execute("SELECT id, path FROM domains WHERE key='legal'").fetchone()
    libraries.subscribe(conn, domain_id=legal["id"], library_key="cases", created_by="t")

    # The vector library in the same scope still answers.
    _qdrant_library(conn, sources={"admin": {"match": {"category": "行政法规"}}})
    libraries.subscribe(conn, domain_id=legal["id"], library_key="law-library", created_by="t")
    monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")
    stub = _Stub(lambda url, body: {"result": []})
    monkeypatch.setattr(library_index, "_http_post", stub)
    hits = library_index.search(conn, domain_path="legal", query="x",
                                embed=lambda t: [[0.1] * 1024])
    assert hits == []                     # no crash from the text-only library
    assert stub.calls                     # the vector library was still queried
