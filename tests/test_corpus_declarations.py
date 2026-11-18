"""Corpus declarations are checkable (§7.11).

A declaration used to be a list of free-form names nobody validated, so a domain
could declare "I need the statute corpus" and never get it — with no signal
anywhere. These tests pin the three states a declaration entry can now be in, and
the one thing that must not happen:

- a bound entry (``library:<lib>/<src>``) that the domain's scope grants → covered;
- a bound entry it does not grant → **not covered**, named;
- a legacy free-form label → unknown, never counted as covered (that would be the
  green that hides the gap);
- saving a template that names a nonexistent library source → refused.
"""

from __future__ import annotations

import pytest

from src.bench import declarations, libraries, templates
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(
        empty_db, name="tpl", created_by="t",
        schema={
            "entity_types": ["clause"], "concept_structures": {"clause": ["id"]},
            "relationship_kinds": ["cites_law"], "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
        },
    )
    for key, path in (("legal", "legal"), ("cr", "legal/cr")):
        parent = None if key == "legal" else empty_db.execute(
            "SELECT id FROM domains WHERE key='legal'").fetchone()["id"]
        empty_db.execute(
            "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
            "SELECT %s,%s,id,1,'t',%s,%s FROM ontology_templates ORDER BY id LIMIT 1",
            (key, key.upper(), parent, path),
        )
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _library(conn, *, subscribe_to: str | None = "legal",
             sources: tuple[str, ...] = ("statutes", "local")) -> None:
    libraries.create_library(conn, library_key="law-library", name="法规大库", created_by="t",
                             backend="qdrant", dims=1024,
                             location={"url_env": "QDRANT_URL", "collection": "law_chunks_v2"})
    for s in sources:
        libraries.add_source(conn, library_key="law-library", source_key=s, uri="x", created_by="t")
    if subscribe_to:
        dom = conn.execute("SELECT id FROM domains WHERE key=%s", (subscribe_to,)).fetchone()
        libraries.subscribe(conn, domain_id=dom["id"], library_key="law-library",
                            created_by="t", source_filter=["statutes"])
    conn.commit()


def test_parse_splits_bound_refs_from_legacy_labels():
    refs, legacy = declarations.parse(
        {"source_types": ["library:law-library/statutes", "stored_clauses"]}
    )
    assert refs == [("law-library", "statutes")]
    assert legacy == ["stored_clauses"]


@pytest.mark.parametrize("bad", ["library:onlylib", "library:a/b/c", "library:/src"])
def test_malformed_ref_is_refused(bad):
    with pytest.raises(ValueError, match="corpus declaration"):
        declarations.parse({"source_types": [bad]})


def test_granted_entry_is_covered_and_ungranted_is_named(conn):
    _library(conn)
    status = declarations.resolve(
        conn, domain_path="legal",
        decl={"source_types": ["library:law-library/statutes", "library:law-library/local"]},
    )
    by_entry = {e["entry"]: e for e in status["entries"]}
    assert by_entry["library:law-library/statutes"]["satisfied"] is True
    assert by_entry["library:law-library/local"]["satisfied"] is False
    assert [e["source_key"] for e in status["missing"]] == ["local"]
    assert status["all_satisfied"] is False


def test_child_inherits_coverage(conn):
    _library(conn)
    status = declarations.resolve(
        conn, domain_path="legal/cr",
        decl={"source_types": ["library:law-library/statutes"]},
    )
    assert status["all_satisfied"] is True


def test_legacy_label_is_unknown_not_covered(conn):
    _library(conn)
    status = declarations.resolve(
        conn, domain_path="legal", decl={"source_types": ["stored_clauses"]}
    )
    assert status["entries"][0]["satisfied"] is None
    # Unknown entries do not make a domain look satisfied-by-declaration.
    assert status["all_satisfied"] is True  # nothing *missing* …
    assert status["entries"][0]["reason"].startswith("free-form")


def test_check_refs_rejects_unknown_library(conn):
    _library(conn)
    with pytest.raises(ValueError, match="unknown library"):
        declarations.check_refs(conn, {"source_types": ["library:ghost/statutes"]})


def test_check_refs_rejects_unknown_source(conn):
    _library(conn)
    with pytest.raises(ValueError, match="no source"):
        declarations.check_refs(conn, {"source_types": ["library:law-library/ghost"]})


def test_check_refs_accepts_known_refs(conn):
    _library(conn)
    declarations.check_refs(conn, {"source_types": ["library:law-library/statutes"]})


def test_text_sources_are_tuples_not_rows(conn):
    """`register_libraries.TEXT_SOURCES` holds tuples; the count step must not
    subscript them by name (that raised `tuple indices must be integers` and was
    swallowed as "counts unavailable")."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import register_libraries as rl
    finally:
        sys.path.pop(0)

    # 4 元组：第 4 项是块侧列映射（add-gov-concept-layer）。块表的主键/正文列名
    # 不是平台默认值——政务块表是 id/chunk_text，没有 chunk_id/title。
    assert all(isinstance(row, tuple) and len(row) == 4 for row in rl.TEXT_SOURCES)
    # Exactly the expression the script now uses.
    allowed = {key for key, _label, _table, _columns in rl.TEXT_SOURCES}
    assert allowed == {"gov", "news", "papers", "screenplay"}
    # 有映射的源必须真的声明 id/text 两项，否则取样器又要靠猜。
    for key, _label, _table, columns in rl.TEXT_SOURCES:
        if columns:
            assert {"id", "text"} <= set(columns), (key, columns)
