"""Corpus documents: browse a store, then take a slice into the ontology (C6).

The claims pinned here are the ones that fail quietly in production:

- **a document list must not be invented.** Titles come from the store's payload
  through the source's own declared mapping; a source that never declared one is
  a named error, not an empty list.
- **unreachable is not empty.** A dead Qdrant raises; the catalog never answers 0.
- **clause cuts are deterministic and verbatim.** An article spanning two chunks
  is assembled, not truncated; a chapter heading is not an article; a document
  with no article headers says so.
- **a batch is all or nothing.** Half a document's articles in the ontology is a
  state nobody can explain later, so the bulk write either lands whole or not at
  all.

No network: Qdrant is answered by an in-memory fake keyed on the request body.
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.bench import authoring, corpus_catalog, libraries
from src.search import library_index


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
            "entity_types": ["law", "clause", "concept"],
            "concept_structures": {"law": ["id"], "clause": ["id"]},
            "relationship_kinds": ["defines"],
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


MAPPING = {
    "id": "doc_key",
    "title": "doc_title",
    "text": "body",
    "order": "seq",
    "kind": "doc_kind",
    "status": "doc_status",
    "publish": "doc_publish",
    "unit_kind": "law",
    "clause_kind": "clause",
}


def _library(conn, *, mapping: dict | None = MAPPING, sources=("statutes",)) -> dict:
    libraries.create_library(
        conn, library_key="law-library", name="law-library", created_by="t",
        backend="qdrant", embedding_model="Qwen/Qwen3-Embedding-0.6B", dims=1024,
        location={"url_env": "TEST_QDRANT_URL", "collection": "corpus"},
    )
    for key in sources:
        rule: dict = {"match": {"category": [key]}}
        if mapping is not None:
            rule["document"] = mapping
        libraries.add_source(
            conn, library_key="law-library", source_key=key, uri=f"collection:corpus/{key}",
            created_by="t", source_kind="payload-filter", ingest_rule=rule,
        )
    return libraries.get_library(conn, library_key="law-library")


class _FakeQdrant:
    """Answers facet/scroll from ``{doc_id: [chunk_text, …]}``."""

    def __init__(self, docs: dict[str, list[dict]], *, title: dict[str, str] | None = None):
        self.docs = docs
        self.titles = title or {}
        self.calls: list[str] = []

    def __call__(self, url, *, json=None, headers=None, timeout=None):  # noqa: A002
        path = url.split("6333", 1)[-1] if "6333" in url else url
        self.calls.append(path)
        if path.endswith("/facet"):
            hits = [{"value": doc_id, "count": len(chunks)}
                    for doc_id, chunks in self.docs.items()]
            payload = {"result": {"hits": hits}}
        elif path.endswith("/points/scroll"):
            payload = {"result": {"points": self._scroll(json or {})}}
        else:  # pragma: no cover - unexpected endpoint is a test failure
            raise AssertionError(f"unexpected call to {url}")
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    def _scroll(self, body: dict) -> list[dict]:
        must = (body.get("filter") or {}).get("must") or []
        id_clause = next((c for c in must if c["key"] == "doc_key"), {})
        match = id_clause.get("match") or {}
        if "any" in match:
            ids = [str(v) for v in match["any"]]
        elif "value" in match:
            ids = [str(match["value"])]
        else:
            ids = list(self.docs)
        out = []
        for doc_id in ids:
            for chunk in self.docs.get(doc_id, []):
                if "any" in match and chunk["seq"] != 0:
                    continue
                out.append({
                    "id": f"{doc_id}-{chunk['seq']}",
                    "payload": {
                        "doc_key": doc_id,
                        "doc_title": self.titles.get(doc_id) or f"Document {doc_id}",
                        "body": chunk["text"],
                        "seq": chunk["seq"],
                        "doc_kind": chunk.get("kind"),
                        "doc_status": chunk.get("status"),
                        "doc_publish": chunk.get("publish"),
                    },
                })
        return out[: int(body.get("limit") or 100)]


@pytest.fixture()
def fake(monkeypatch):
    def install(docs, *, title=None):
        stub = _FakeQdrant(docs, title=title)
        monkeypatch.setattr(library_index, "_http_post", stub)
        monkeypatch.setenv("TEST_QDRANT_URL", "http://qdrant.test:6333")
        return stub

    return install


# ── declarations ─────────────────────────────────────────────────────────────


def test_a_source_without_a_document_mapping_is_a_named_error(conn):
    _library(conn, mapping=None)
    with pytest.raises(corpus_catalog.DocumentMappingError, match="statutes"):
        corpus_catalog.documents(conn, library_key="law-library", source_key="statutes")


def test_mapping_must_name_the_required_fields(conn):
    _library(conn, mapping={"id": "doc_key", "title": "doc_title"})
    with pytest.raises(corpus_catalog.DocumentMappingError, match="text"):
        corpus_catalog.documents(conn, library_key="law-library", source_key="statutes")


def test_mapping_refuses_an_unsafe_field_name(conn):
    _library(conn, mapping={**MAPPING, "text": "body; DROP TABLE x"})
    with pytest.raises(corpus_catalog.DocumentMappingError, match="unsafe"):
        corpus_catalog.documents(conn, library_key="law-library", source_key="statutes")


# ── browse ───────────────────────────────────────────────────────────────────


def test_documents_lists_documents_not_chunks(conn, fake):
    _library(conn)
    fake({"7": [{"seq": 0, "text": "第一条 …", "kind": "法律", "status": "有效"},
                {"seq": 1, "text": "第二条 …"}],
          "9": [{"seq": 0, "text": "第一条 …", "kind": "法律"}]},
         title={"7": "中华人民共和国合同法", "9": "中华人民共和国保险法"})
    page = corpus_catalog.documents(conn, library_key="law-library", source_key="statutes")
    assert page["total"] == 2
    assert page["partial"] is False
    assert [r["title"] for r in page["rows"]] == ["中华人民共和国合同法", "中华人民共和国保险法"]
    assert page["rows"][0]["chunks"] == 2


def test_documents_marks_what_is_already_adopted(conn, fake):
    _library(conn)
    fake({"7": [{"seq": 0, "text": "第一条 …"}]}, title={"7": "中华人民共和国合同法"})
    authoring.authoring_create_unit(
        conn, domain_key="legal", kind="law", external_key="合同法",
        body="# 合同法", operator="t",
    )
    page = corpus_catalog.documents(
        conn, library_key="law-library", source_key="statutes", domain_key="legal")
    # The key, not the kind: "already in the ontology as 合同法" is the useful
    # fact when two spellings of one title exist.
    assert page["rows"][0]["adopted_as"] == "合同法"


def test_unreachable_store_is_not_an_empty_catalog(conn, fake, monkeypatch):
    _library(conn)
    def boom(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    fake({})
    monkeypatch.setattr(library_index, "_http_post", boom)
    with pytest.raises(corpus_catalog.StoreError, match="connection refused"):
        corpus_catalog.documents(conn, library_key="law-library", source_key="statutes")


def test_window_says_when_the_list_is_cut(conn, fake):
    _library(conn)
    docs = {str(i): [{"seq": 0, "text": "第一条 …"}] for i in range(5)}
    fake(docs)
    page = corpus_catalog.documents(
        conn, library_key="law-library", source_key="statutes", window=3, limit=2)
    assert page["rows"] and len(page["rows"]) == 2
    assert page["partial"] is True
    assert page["window"] == 3


def test_title_search_stays_inside_the_window_and_says_so(conn, fake):
    _library(conn)
    docs = {str(i): [{"seq": 0, "text": "第一条 …"}] for i in range(4)}
    fake(docs, title={"0": "A法", "1": "B法", "2": "C法", "3": "D法"})
    page = corpus_catalog.documents(
        conn, library_key="law-library", source_key="statutes", q="C法", window=4)
    assert [r["title"] for r in page["rows"]] == ["C法"]
    assert page["total"] == 1


# ── clause splitting ─────────────────────────────────────────────────────────


def _chunks(*texts):
    return [{"chunk_id": f"c{i}", "order": i, "text": text, "title": "某法"}
            for i, text in enumerate(texts)]


def test_split_reassembles_an_article_across_chunks():
    split = corpus_catalog.split_clauses(_chunks(
        "第一条 总则的内容。\n第二条 跨块的",
        "前半段，仍在第二条里。\n第三条 结束。",
    ))
    by_no = {c["no"]: c for c in split["clauses"]}
    assert set(by_no) == {1, 2, 3}
    assert "跨块的前半段" in by_no[2]["text"].replace("\n", "")
    assert by_no[3]["text"].startswith("第三条")
    assert by_no[2]["chunk_id"] == "c0"


def test_split_ignores_structural_headings():
    split = corpus_catalog.split_clauses(_chunks(
        "第一章 总则\n第一条 内容。\n第二章 合同的订立\n第二条 内容。",
    ))
    assert [c["no"] for c in split["clauses"]] == [1, 2]


def test_split_reports_a_document_with_no_articles():
    split = corpus_catalog.split_clauses(_chunks("这是一份决定，没有条文结构。"))
    assert split["clauses"] == []
    assert split["reason"] == "no_clause_headers"


def test_split_counts_repeated_article_numbers_once():
    split = corpus_catalog.split_clauses(_chunks(
        "第一条 甲。\n第一条 乙。\n第二条 丙。",
    ))
    assert [c["no"] for c in split["clauses"]] == [1, 2]
    assert split["duplicates"] == 1


def test_split_marks_an_article_it_could_not_finish():
    split = corpus_catalog.split_clauses(
        _chunks("第一条 甲。\n第二条 只有半截"), document_complete=False)
    by_no = {c["no"]: c for c in split["clauses"]}
    assert by_no[2]["truncated"] is True
    assert by_no[1]["truncated"] is False


def test_split_does_not_treat_a_citation_as_a_header():
    split = corpus_catalog.split_clauses(_chunks(
        "第一条 依照民法典第五百八十五条处理。",
    ))
    assert [c["no"] for c in split["clauses"]] == [1]


# ── adoption ─────────────────────────────────────────────────────────────────


def test_adopt_document_writes_one_unit_with_corpus_evidence(conn, fake):
    _library(conn)
    fake({"7": [{"seq": 0, "text": "第一条 内容。", "kind": "法律", "status": "有效"}]},
         title={"7": "中华人民共和国合同法"})
    out = corpus_catalog.adopt_document(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t")
    assert out["key"] == "合同法"
    assert out["created"] is True
    unit = authoring.authoring_get_unit(conn, domain_key="legal", kind="law",
                                        external_key="合同法")
    assert unit["attrs"]["corpus"]["doc_id"] == "7"
    assert unit["attrs"]["evidence"]["chunk_id"] == "7-0"


def test_adopt_document_is_idempotent(conn, fake):
    _library(conn)
    fake({"7": [{"seq": 0, "text": "第一条 内容。"}]}, title={"7": "中华人民共和国合同法"})
    corpus_catalog.adopt_document(conn, domain_key="legal", library_key="law-library",
                                  source_key="statutes", doc_id="7", operator="t")
    again = corpus_catalog.adopt_document(conn, domain_key="legal", library_key="law-library",
                                          source_key="statutes", doc_id="7", operator="t")
    assert again["created"] is False
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_units WHERE namespace='legal' AND kind='law'"
    ).fetchone()
    assert rows["n"] == 1


def test_adopt_document_needs_a_declared_unit_kind(conn, fake):
    _library(conn, mapping={k: v for k, v in MAPPING.items() if k != "unit_kind"})
    fake({"7": [{"seq": 0, "text": "第一条 内容。"}]})
    with pytest.raises(corpus_catalog.DocumentMappingError, match="unit_kind"):
        corpus_catalog.adopt_document(conn, domain_key="legal", library_key="law-library",
                                      source_key="statutes", doc_id="7", operator="t")


def test_adopt_clauses_uses_the_shared_clause_key_and_is_atomic(conn, fake):
    _library(conn)
    fake({"7": [{"seq": 0, "text": "第一条 甲。\n第二条 乙。"}]},
         title={"7": "中华人民共和国合同法"})
    out = corpus_catalog.adopt_clauses(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t")
    assert out["adopted"] == 2
    keys = [r["external_key"] for r in conn.execute(
        "SELECT external_key FROM knowledge_units WHERE namespace='legal' AND kind='clause' "
        "ORDER BY external_key").fetchall()]
    assert keys == ["合同法#第1条", "合同法#第2条"]


def test_adopt_clauses_reports_capped_and_remaining(conn, fake):
    _library(conn)
    text = "".join(f"第{i}条 内容。\n" for i in range(1, 6))
    fake({"7": [{"seq": 0, "text": text}]}, title={"7": "某法"})
    out = corpus_catalog.adopt_clauses(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t", limit=3)
    assert out["adopted"] == 3
    assert out["capped"] is True
    assert out["remaining"] == 2


def test_adopt_clauses_with_no_headers_writes_nothing(conn, fake):
    _library(conn)
    fake({"7": [{"seq": 0, "text": "一份没有条文结构的决定。"}]}, title={"7": "某决定"})
    out = corpus_catalog.adopt_clauses(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t")
    assert out["adopted"] == 0
    assert out["reason"] == "no_clause_headers"
    assert conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"] == 0


def test_bulk_create_refuses_a_kind_outside_the_vocabulary_and_writes_nothing(conn):
    with pytest.raises(ValueError, match="not in the entity_types vocabulary"):
        authoring.authoring_create_units(
            conn, domain_key="legal", operator="t",
            units=[{"kind": "clause", "external_key": "某法#第1条", "body": "甲"},
                   {"kind": "made_up", "external_key": "某法#第2条", "body": "乙"}],
        )
    assert conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"] == 0


def test_bulk_create_refuses_duplicate_keys(conn):
    with pytest.raises(ValueError, match="duplicate key"):
        authoring.authoring_create_units(
            conn, domain_key="legal", operator="t",
            units=[{"kind": "clause", "external_key": "某法#第1条", "body": "甲"},
                   {"kind": "clause", "external_key": "某法#第1条", "body": "乙"}],
        )
    assert conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"] == 0


def test_bulk_create_writes_one_event_per_unit(conn):
    written = authoring.authoring_create_units(
        conn, domain_key="legal", operator="t",
        units=[{"kind": "clause", "external_key": "某法#第1条", "body": "甲"},
               {"kind": "clause", "external_key": "某法#第2条", "body": "乙"}],
    )
    assert len(written) == 2
    events = conn.execute("SELECT COUNT(*) AS n FROM authoring_events").fetchone()
    assert events["n"] == 2


def test_a_second_click_continues_instead_of_rewriting_the_first_page(conn, fake):
    """The cap must not become a ceiling: clicking again has to make progress."""
    _library(conn)
    text = "".join(f"第{i}条 内容{i}。\n" for i in range(1, 8))
    fake({"7": [{"seq": 0, "text": text}]}, title={"7": "某法"})
    first = corpus_catalog.adopt_clauses(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t", limit=3)
    second = corpus_catalog.adopt_clauses(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t", limit=3)
    third = corpus_catalog.adopt_clauses(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t", limit=3)
    assert (first["adopted"], first["remaining"]) == (3, 4)
    assert (second["adopted"], second["remaining"]) == (3, 1)
    assert (third["adopted"], third["remaining"]) == (1, 0)
    keys = sorted(r["external_key"] for r in conn.execute(
        "SELECT external_key FROM knowledge_units WHERE kind='clause'").fetchall())
    assert keys == [f"某法#第{i}条" for i in range(1, 8)]


def test_adopting_everything_already_present_says_nothing_new(conn, fake):
    _library(conn)
    fake({"7": [{"seq": 0, "text": "第一条 甲。\n第二条 乙。"}]}, title={"7": "某法"})
    corpus_catalog.adopt_clauses(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t")
    again = corpus_catalog.adopt_clauses(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t")
    assert again["adopted"] == 0
    assert again["reason"] == "nothing_new"


def test_adoption_sees_existing_keys_past_the_entity_list_cap(conn, fake, monkeypatch):
    """The picker list is capped at 1000; "already adopted" must not be.

    Measured in production: a 1,208-article code never converged because the
    existing-key set stopped at the cap and the same 200 articles were rewritten
    every click.
    """
    from src.bench import authoring as authoring_mod

    # Pretend this many articles already landed, without writing them all.
    fake({"7": [{"seq": 0, "text": "".join(f'第{i}条 甲{i}。\n' for i in range(1, 6))}]},
         title={"7": "某法"})
    _library(conn)
    monkeypatch.setattr(
        authoring_mod, "authoring_live_entities",
        lambda conn, domain_key, limit=1000: (_ for _ in ()).throw(
            AssertionError("adoption must not read the capped picker list")),
    )
    out = corpus_catalog.adopt_clauses(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t")
    assert out["adopted"] == 5


# ── corpora whose documents and chunks are different tables ──────────────────


@pytest.fixture()
def split_tables(conn):
    """A document table + a chunk table, the shape most text corpora have."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS t_docs ("
        "  id bigint PRIMARY KEY, domain text, title text, content text, status text)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS t_chunks ("
        "  id bigint PRIMARY KEY, document_id bigint, chunk_no int, chunk_text text)"
    )
    conn.execute("DELETE FROM t_docs")
    conn.execute("DELETE FROM t_chunks")
    conn.execute(
        "INSERT INTO t_docs VALUES (1,'gov','某市政务公开要点','第一条 公开范围\n第二条 公开方式','现行')"
    )
    conn.execute(
        "INSERT INTO t_chunks VALUES (10,1,0,'第一条 公开范围'),(11,1,1,'第二条 公开方式')"
    )
    conn.commit()
    libraries.create_library(
        conn, library_key="text-library", name="text-library", created_by="t",
        backend="pgvector-external", embedding_model="m", dims=1024,
        location={"dsn_env": "database_url"},
    )
    libraries.add_source(
        conn, library_key="text-library", source_key="gov", uri="t_chunks",
        created_by="t", source_kind="external-table",
        ingest_rule={"document": {"table": "t_docs", "id": "id", "title": "title",
                                  "text": "content", "status": "status",
                                  "doc_ref": "document_id", "unit_kind": "law"},
                     "where": {"domain": "gov"}},
    )
    dom = conn.execute("SELECT id FROM domains WHERE key='legal'").fetchone()
    libraries.subscribe(conn, domain_id=dom["id"], library_key="text-library", created_by="t")
    conn.commit()


def test_documents_come_from_the_document_table_and_count_chunks(conn, split_tables):
    page = corpus_catalog.documents(conn, library_key="text-library", source_key="gov")
    assert page["total"] == 1
    row = page["rows"][0]
    assert row["title"] == "某市政务公开要点"
    assert row["chunks"] == 2          # counted from the chunk table, not the doc table


def test_a_document_row_is_its_own_text(conn, split_tables):
    fetched = corpus_catalog.document_chunks(
        conn, library_key="text-library", source_key="gov", doc_id="1")
    assert len(fetched["chunks"]) == 1
    assert fetched["chunks"][0]["text"].startswith("第一条 公开范围")
    split = corpus_catalog.split_clauses(fetched["chunks"])
    assert [c["no"] for c in split["clauses"]] == [1, 2]


def test_document_key_previews_exactly_what_adoption_writes(conn, fake):
    """A preview/cleanup path must not compute a different key than the write."""
    _library(conn)
    fake({"7": [{"seq": 0, "text": "第一条 内容。"}]}, title={"7": "中华人民共和国合同法"})
    preview = corpus_catalog.document_key(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7")
    written = corpus_catalog.adopt_document(
        conn, domain_key="legal", library_key="law-library", source_key="statutes",
        doc_id="7", operator="t")
    assert preview == written["key"] == "合同法"
