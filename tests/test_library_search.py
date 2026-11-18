"""Library retrieval (change add-domain-tree-and-shared-libraries §2).

Pins the three behaviours a naive implementation gets wrong:

- a top-k never contains a sibling's or a narrowed-away source's content
  (filter happens before ranking);
- "no match" (``[]``) and "nothing to search" (``NotSubscribed``) stay
  distinguishable — returning ``[]`` for an unsubscribed domain would read as a
  successful empty search;
- ingest is idempotent per ``(library, doc_path)`` and refuses a dimension that
  disagrees with the library declaration.

Embeddings are injected, so no network and no model download in this suite.
"""

from __future__ import annotations

import pytest

from src.bench import libraries
from src.eval import store as eval_store
from src.eval.store import ensure_schema
from src.search import library_index
from src.search.library_index import NotSubscribed


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    yield empty_db


def _embed(texts: list[str]) -> list[list[float]]:
    """Deterministic 4-dim embedding: counts of marker words, then padded."""
    out = []
    for t in texts:
        low = t.lower()
        out.append(
            [
                float(low.count("alpha")),
                float(low.count("beta")),
                float(low.count("gamma")),
                1.0,
            ]
        )
    return out


def _world(conn):
    tid = conn.execute(
        "INSERT INTO ontology_templates (name, version, schema, created_by) "
        "VALUES ('tpl', 1, '{\"entity_types\":[\"x\"],\"relationship_kinds\":[\"r\"],"
        "\"tier_vocabulary\":[\"raw\"],\"sensitivity_vocabulary\":[\"public\"],"
        "\"corpus_declaration\":{\"source_types\":[\"uploaded\"]}}', 't') RETURNING id"
    ).fetchone()["id"]
    root = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "VALUES ('legal','Legal',%s,1,'t','legal') RETURNING id, path",
        (tid,),
    ).fetchone()
    child = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
        "VALUES ('cr','Contract Review',%s,1,'t',%s,'legal/cr') RETURNING id, path",
        (tid, root["id"]),
    ).fetchone()
    sibling = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
        "VALUES ('lp','Litigation',%s,1,'t',%s,'legal/lp') RETURNING id, path",
        (tid, root["id"]),
    ).fetchone()
    conn.commit()
    libraries.create_library(conn, library_key="law", name="Law", created_by="t", dims=4)
    for key in ("statutes", "contracts", "pleadings"):
        libraries.add_source(conn, library_key="law", source_key=key, uri=f"s3://b/{key}", created_by="t")
    return dict(root), dict(child), dict(sibling)


def test_ingest_is_idempotent_per_document(conn):
    root, _, _ = _world(conn)
    docs = [{"path": "d1.md", "text": "alpha " * 300}]
    first = library_index.ingest_documents(
        conn, library_key="law", scope_path=root["path"], source_key="contracts",
        documents=docs, embed=_embed, chunk_size=100, chunk_overlap=10,
    )
    second = library_index.ingest_documents(
        conn, library_key="law", scope_path=root["path"], source_key="contracts",
        documents=docs, embed=_embed, chunk_size=100, chunk_overlap=10,
    )
    assert first["chunks"] == second["chunks"]
    n = conn.execute("SELECT COUNT(*) AS n FROM corpus_chunks").fetchone()["n"]
    assert n == first["chunks"], "re-ingest must replace, not duplicate"


def test_ingest_refuses_unknown_source(conn):
    root, _, _ = _world(conn)
    with pytest.raises(ValueError, match="not registered"):
        library_index.ingest_documents(
            conn, library_key="law", scope_path=root["path"], source_key="nope",
            documents=[{"path": "d", "text": "alpha"}], embed=_embed,
        )


def test_ingest_refuses_dimension_mismatch(conn):
    root, _, _ = _world(conn)
    with pytest.raises(ValueError, match="dimension"):
        library_index.ingest_documents(
            conn, library_key="law", scope_path=root["path"], source_key="contracts",
            documents=[{"path": "d", "text": "alpha"}],
            embed=lambda texts: [[1.0, 2.0] for _ in texts],
        )


def test_search_is_scoped_to_the_domains_sources(conn):
    root, child, _ = _world(conn)
    libraries.subscribe(conn, domain_id=root["id"], library_key="law", created_by="t")
    libraries.subscribe(
        conn, domain_id=child["id"], library_key="law", created_by="t",
        source_filter=["contracts"],
    )
    library_index.ingest_documents(
        conn, library_key="law", scope_path=root["path"], source_key="contracts",
        documents=[{"path": "c.md", "text": "alpha alpha"}], embed=_embed,
    )
    library_index.ingest_documents(
        conn, library_key="law", scope_path=root["path"], source_key="pleadings",
        documents=[{"path": "p.md", "text": "alpha alpha"}], embed=_embed,
    )
    hits_root = library_index.search(conn, domain_path="legal", query="alpha", embed=_embed)
    hits_child = library_index.search(conn, domain_path="legal/cr", query="alpha", embed=_embed)
    assert {h["source_key"] for h in hits_root} == {"contracts", "pleadings"}
    assert {h["source_key"] for h in hits_child} == {"contracts"}


def test_sibling_content_is_invisible(conn):
    root, child, sibling = _world(conn)
    libraries.subscribe(
        conn, domain_id=root["id"], library_key="law", created_by="t",
        source_filter=["contracts"],
    )
    libraries.subscribe(
        conn, domain_id=child["id"], library_key="law", created_by="t",
        source_filter=["contracts"],
    )
    libraries.subscribe(
        conn, domain_id=sibling["id"], library_key="law", created_by="t",
        source_filter=["pleadings"],
    )
    library_index.ingest_documents(
        conn, library_key="law", scope_path=sibling["path"], source_key="pleadings",
        documents=[{"path": "s.md", "text": "beta beta"}], embed=_embed,
    )
    # The sibling's chunks exist in the shared table but the parent's scope
    # (contracts only) must not reach them.
    assert library_index.search(conn, domain_path="legal", query="beta", embed=_embed) == []


def test_unsubscribed_domain_is_not_an_empty_result(conn):
    root, _, _ = _world(conn)
    other = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "VALUES ('bank','Bank',(SELECT id FROM ontology_templates LIMIT 1),1,'t','bank') "
        "RETURNING id, path"
    ).fetchone()
    conn.commit()
    with pytest.raises(NotSubscribed):
        library_index.search(conn, domain_path=other["path"], query="alpha", embed=_embed)
    # …while a subscribed domain with nothing ingested honestly returns [].
    libraries.subscribe(conn, domain_id=root["id"], library_key="law", created_by="t")
    assert library_index.search(conn, domain_path="legal", query="alpha", embed=_embed) == []


def test_explain_scope_marks_origin(conn):
    root, child, _ = _world(conn)
    libraries.subscribe(conn, domain_id=root["id"], library_key="law", created_by="t")
    libraries.subscribe(
        conn, domain_id=child["id"], library_key="law", created_by="t",
        source_filter=["contracts"],
    )
    parent = library_index.explain_scope(conn, domain_path="legal")
    child_view = library_index.explain_scope(conn, domain_path="legal/cr")
    assert parent["libraries"][0]["origin"] == "own"
    assert child_view["libraries"][0]["origin"] == "own"
    assert child_view["libraries"][0]["sources"] == ["contracts"]
