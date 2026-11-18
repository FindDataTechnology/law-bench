"""Shared corpus libraries + domain tree (change add-domain-tree-and-shared-libraries, §1).

Covers the storage contract the rest of the change builds on:

- the domain tree (parent_id + materialized path) and its prefix semantics;
- library / source / subscription records, including the "unknown source is
  refused" gate so a typo cannot create a silently empty scope;
- ``effective_sources``: parent → child inheritance, narrowing only, and the
  hard refusal of a child that tries to widen what its parent granted
  (spec: 继承型取材 — 子域不能越权扩大);
- the additive migrations: pre-tree domains get path=key, the catch-all
  ``knowledge_units.namespace='default'`` is repointed at the first domain, and
  legacy rubrics acquire that domain as owner.
"""

from __future__ import annotations

import pytest

from src.bench import libraries
from src.eval import store as eval_store
from src.eval.store import ensure_schema


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    yield empty_db


def _make_domain(conn, key: str, *, parent=None, template_id: int = 1) -> dict:
    """Insert a domain row directly — the tree shape is what is under test."""
    parent_id = None
    path = key
    if parent is not None:
        parent_id = parent["id"]
        path = f"{parent['path']}/{key}"
    row = conn.execute(
        """
        INSERT INTO domains (key, name, template_id, template_version, created_by, parent_id, path)
        VALUES (%s, %s, %s, 1, 'tester', %s, %s)
        RETURNING id, key, path, parent_id
        """,
        (path.replace("/", "-"), f"Domain {path}", template_id, parent_id, path),
    ).fetchone()
    conn.commit()
    return dict(row)


def _template(conn) -> int:
    row = conn.execute(
        """
        INSERT INTO ontology_templates (name, version, schema, created_by)
        VALUES ('tpl-lib', 1, %s, 'tester') RETURNING id
        """,
        (
            '{"entity_types":["clause"],"relationship_kinds":["references"],'
            '"tier_vocabulary":["raw","bronze","silver","gold"],'
            '"sensitivity_vocabulary":["public","internal","confidential"],'
            '"corpus_declaration":{"source_types":["uploaded"]}}',
        ),
    ).fetchone()
    conn.commit()
    return row["id"]


# ── tree ─────────────────────────────────────────────────────────────────────


def test_domain_path_is_unique_and_parent_indexed(conn):
    tid = _template(conn)
    root = _make_domain(conn, "legal", template_id=tid)
    child = _make_domain(conn, "contract-review", parent=root, template_id=tid)
    assert root["path"] == "legal"
    assert child["path"] == "legal/contract-review"
    with pytest.raises(Exception):
        _make_domain(conn, "legal", template_id=tid)  # duplicate path


def test_ancestors_helper_is_root_first():
    assert libraries._ancestors("legal/a/b") == ["legal", "legal/a", "legal/a/b"]
    assert libraries._ancestors("legal") == ["legal"]


# ── libraries & sources ──────────────────────────────────────────────────────


def test_create_library_and_duplicate_key_refused(conn):
    lib = libraries.create_library(conn, library_key="law-library", name="法规库", created_by="t")
    assert lib["library_key"] == "law-library"
    assert lib["dims"] == 2048
    with pytest.raises(Exception):
        libraries.create_library(conn, library_key="law-library", name="重复", created_by="t")


def test_unknown_backend_refused(conn):
    with pytest.raises(ValueError):
        libraries.create_library(
            conn, library_key="x", name="x", created_by="t", backend="pinecone"
        )


def test_add_source_and_unknown_source_refused(conn):
    libraries.create_library(conn, library_key="law-library", name="法规库", created_by="t")
    src = libraries.add_source(
        conn, library_key="law-library", source_key="statutes", uri="s3://b/statutes", created_by="t"
    )
    assert src["source_key"] == "statutes"
    with pytest.raises(ValueError):
        libraries.add_source(
            conn, library_key="missing", source_key="x", uri="u", created_by="t"
        )


# ── subscriptions ────────────────────────────────────────────────────────────


def _seeded(conn):
    tid = _template(conn)
    root = _make_domain(conn, "legal", template_id=tid)
    child = _make_domain(conn, "contract-review", parent=root, template_id=tid)
    libraries.create_library(conn, library_key="law-library", name="法规库", created_by="t")
    for key in ("statutes", "contracts", "clauses"):
        libraries.add_source(
            conn, library_key="law-library", source_key=key, uri=f"s3://b/{key}", created_by="t"
        )
    return root, child


def test_root_subscribing_everything_sees_every_source(conn):
    root, _ = _seeded(conn)
    libraries.subscribe(conn, domain_id=root["id"], library_key="law-library", created_by="t")
    scope = libraries.effective_sources(conn, domain_path="legal")
    assert scope == {"law-library": {"statutes", "contracts", "clauses"}}


def test_child_inherits_then_narrows(conn):
    root, child = _seeded(conn)
    libraries.subscribe(conn, domain_id=root["id"], library_key="law-library", created_by="t")
    libraries.subscribe(
        conn,
        domain_id=child["id"],
        library_key="law-library",
        created_by="t",
        source_filter=["contracts", "clauses"],
    )
    parent_scope = libraries.effective_sources(conn, domain_path="legal")
    child_scope = libraries.effective_sources(conn, domain_path="legal/contract-review")
    assert parent_scope["law-library"] == {"statutes", "contracts", "clauses"}
    assert child_scope["law-library"] == {"contracts", "clauses"}


def test_child_cannot_widen_parent_scope(conn):
    root, child = _seeded(conn)
    libraries.subscribe(
        conn,
        domain_id=root["id"],
        library_key="law-library",
        created_by="t",
        source_filter=["contracts"],
    )
    libraries.subscribe(
        conn,
        domain_id=child["id"],
        library_key="law-library",
        created_by="t",
        source_filter=["contracts", "statutes"],
    )
    with pytest.raises(ValueError, match="widens"):
        libraries.effective_sources(conn, domain_path="legal/contract-review")


def test_child_cannot_introduce_library_parent_lacks(conn):
    root, child = _seeded(conn)
    libraries.create_library(conn, library_key="bank-library", name="银行库", created_by="t")
    libraries.add_source(
        conn, library_key="bank-library", source_key="rates", uri="s3://b/rates", created_by="t"
    )
    libraries.subscribe(conn, domain_id=root["id"], library_key="law-library", created_by="t")
    libraries.subscribe(conn, domain_id=child["id"], library_key="bank-library", created_by="t")
    with pytest.raises(ValueError, match="cannot widen"):
        libraries.effective_sources(conn, domain_path="legal/contract-review")


def test_unsubscribed_domain_gets_empty_scope(conn):
    tid = _template(conn)
    _make_domain(conn, "banking", template_id=tid)
    assert libraries.effective_sources(conn, domain_path="banking") == {}


# ── additive migrations ──────────────────────────────────────────────────────


def test_legacy_rows_are_repointed_at_the_first_domain(conn):
    tid = _template(conn)
    domain = _make_domain(conn, "legal", template_id=tid)
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, created_at, updated_at) "
        "VALUES ('entity', 'default', 'k1', 'body', 'now', 'now')"
    )
    # rubrics predates ensure_schema (a script creates it in deployed DBs), so
    # the legacy shape is recreated here to exercise the backfill honestly.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rubrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            context TEXT,
            source TEXT,
            source_path TEXT,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description) "
        "VALUES ('r1', 'check', 'seed', '/p', 'd')"
    )
    conn.commit()

    # ensure_schema memoizes per database; clearing the memo is exactly what a
    # process restart does, and a restart is when the backfill has to run.
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=conn)
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=conn)  # third pass: the backfill must be idempotent

    unit = conn.execute("SELECT namespace FROM knowledge_units WHERE external_key='k1'").fetchone()
    rubric = conn.execute("SELECT domain_id FROM rubrics WHERE name='r1'").fetchone()
    assert unit["namespace"] == domain["path"]
    assert rubric["domain_id"] == domain["id"]
