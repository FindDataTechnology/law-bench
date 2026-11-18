"""Kernel tests for the domain RAG corpus registry (change
``add-domain-rag-corpus-service``, OpenSpec tasks 1.1/1.2/3.1 + the
resolution branches of 3.2).

Covers ``src/search/resolver.py`` (``resolve_index`` / ``register_corpus`` /
``get_corpus`` / ``list_corpora``), the ``rag_corpora`` legal retro-
registration seed inside ``src.eval.store.ensure_schema``, and the
domain-resolution branches of ``src.search.ingest.run_ingest`` — all with no
HTTP and no live Elasticsearch: the ingest tests stub
``minio_source.load_documents`` and the vector-store write stack at the
``src.search.ingest`` module boundary (the resolution under test happens
before any ES call; the ES-touching parts are never reached with a live
client).

Style: ``tests/test_authoring_kernel.py`` — a module-local ``db_conn``
fixture on the ``empty_db`` per-test database (no schema) running
``ensure_schema``; domains are created through the C1 kernel APIs
(``src.bench.templates`` / ``src.bench.workspaces``).

``src.settings.SEARCH_INDEX_NAME`` is monkeypatched to a sentinel value
BEFORE ``ensure_schema`` runs, proving both the seed and the resolver's
default path read the live setting (function-time attribute read) rather than
an import-time binding.

The legal retro-registration seed only fires when a domain keyed ``legal``
already exists, and ``ensure_schema`` memoizes per database (``_ensured_dbs``)
— so tests that need the seed to re-fire call :func:`_reensure`, which clears
that memo key first (the DDL itself is idempotent, so re-running it is safe
and also exercises the seed's own NOT EXISTS/ON CONFLICT guard).
"""

from __future__ import annotations

import pytest
from llama_index.core import Document

from src.bench import templates as bench_templates
from src.bench import workspaces
from src.eval.store import ensure_schema
from src.search import ingest, resolver

# Sentinel proving the default index is read from the live setting, not from
# an import-time binding (src/settings.py ships the default 'contracts').
CUSTOM_DEFAULT_INDEX = "kidx-default"

# A structurally complete template schema, as the C1 kernel APIs require it
# (same shape as the other workspace suites' VALID_SCHEMA).
VALID_SCHEMA = {
    "entity_types": ["company"],
    "concept_structures": {"indicator": ["name", "unit"]},
    "relationship_kinds": ["belongs_to"],
    "tier_vocabulary": ["gold", "silver", "bronze", "raw"],
    "sensitivity_vocabulary": ["public", "internal", "confidential"],
    "corpus_declaration": {"source_types": []},
}


# --- fixtures + seed helpers ------------------------------------------------- #


@pytest.fixture()
def db_conn(empty_db, monkeypatch):  # noqa: F811 - provided by tests/conftest.py
    """Fresh per-test DB with the full schema; sentinel default index active.

    The monkeypatch MUST be in place before ``ensure_schema`` so the legal
    retro-registration seed binds the sentinel value.
    """
    monkeypatch.setattr("src.settings.SEARCH_INDEX_NAME", CUSTOM_DEFAULT_INDEX)
    ensure_schema(db_path=empty_db)
    yield empty_db


def _reensure(conn) -> None:
    """Re-run ``ensure_schema`` on this DB, bypassing the per-db memoization."""
    from src.eval import store as eval_store

    eval_store._ensured_dbs.discard(conn.info.dbname)
    eval_store.ensure_schema(db_path=conn)


def make_domain(conn, key: str) -> dict:
    """One member domain instantiated from its own template (C1 APIs)."""
    bench_templates.create_template(
        conn, name=f"tpl-{key}", schema=dict(VALID_SCHEMA), created_by="admin-1"
    )
    return workspaces.instantiate_domain(
        conn,
        key=key,
        name=f"Domain {key}",
        template_name=f"tpl-{key}",
        template_version=None,
        created_by="admin-1",
    )


# --- ES/MinIO stubbing for the ingest resolution branches -------------------- #


class _FakeVectorStore:
    """Records the index it was built for and the delete calls it received."""

    def __init__(self, index_name):
        self.index_name = index_name
        self.deleted: list = []

    def delete(self, nodes=None):
        self.deleted.extend(nodes or [])


def _stub_es_write(monkeypatch):
    """Stub the ES write stack on ``src.search.ingest``; return recorders.

    ``get_vector_store`` / ``VectorStoreIndex`` / ``get_embed_model`` /
    ``verify_dimensions`` are replaced so a chunk "write" never touches
    Elasticsearch or the OpenRouter embedding endpoint.
    """
    stores: list[_FakeVectorStore] = []
    inserted: list = []

    class _FakeIndex:
        def __init__(self, vs, storage_context=None, embed_model=None):
            self.vs = vs

        @classmethod
        def from_vector_store(cls, vs, storage_context=None, embed_model=None):
            return cls(vs, storage_context=storage_context, embed_model=embed_model)

        def insert_nodes(self, nodes):
            inserted.extend(nodes)

    def fake_get_vector_store(index_name=None):
        vs = _FakeVectorStore(index_name)
        stores.append(vs)
        return vs

    monkeypatch.setattr(ingest, "get_vector_store", fake_get_vector_store)
    monkeypatch.setattr(ingest, "VectorStoreIndex", _FakeIndex)
    monkeypatch.setattr(ingest, "get_embed_model", lambda: object())
    monkeypatch.setattr(ingest, "verify_dimensions", lambda: 4)
    return stores, inserted


def _stub_load(monkeypatch, with_docs: bool) -> list[dict]:
    """Stub ``minio_source.load_documents`` on ``src.search.ingest``.

    Records every call as ``{"bucket": ..., "prefix": ...}``; returns one tiny
    canned llama-index Document per call when ``with_docs`` (so the run reaches
    the write path) or ``[]`` (so it returns early, proving the resolution
    happened without any write). The recorders see exactly what ``run_ingest``
    resolved — buckets/prefixes from the registration or the legacy call shape.
    """
    calls: list[dict] = []

    def fake_load(prefix=None, bucket=None):
        calls.append({"bucket": bucket, "prefix": prefix})
        if with_docs:
            return [Document(text="保密条款：乙方不得泄露甲方的商业秘密。")]
        return []

    monkeypatch.setattr(ingest, "load_documents", fake_load)
    return calls


# =========================================================================== #
# ensure_schema: legal retro-registration seed (task 1.1)                      #
# =========================================================================== #


def test_ensure_schema_seeds_no_row_without_legal_domain(db_conn):
    """Seed keys on the 'legal' domain specifically: nothing else seeds.

    The fixture's ensure ran on an empty DB (no domains at all); creating a
    NON-legal domain and re-ensuring still leaves the registry empty.
    """
    assert resolver.list_corpora(db_conn) == []
    make_domain(db_conn, "fin")
    _reensure(db_conn)
    assert resolver.list_corpora(db_conn) == []


def test_ensure_schema_seeds_legal_row_once_custom_index_honored(db_conn):
    """Legal domain present -> seed row with the live SEARCH_INDEX_NAME value.

    The domain is registered via the C1 APIs first; the next ensure seeds
    ``rag_corpora`` with index_name == the (sentinel) setting, sources empty,
    and the retro-register operator stamp. Re-ensuring is idempotent: exactly
    one row, unchanged (the seed's NOT EXISTS + ON CONFLICT guard).
    """
    legal = make_domain(db_conn, "legal")
    assert resolver.get_corpus(db_conn, domain_key="legal") is None

    _reensure(db_conn)
    row = resolver.get_corpus(db_conn, domain_key="legal")
    assert row is not None
    assert row["domain_id"] == legal["id"]
    assert row["index_name"] == CUSTOM_DEFAULT_INDEX  # honors the live setting
    assert row["sources"] == []
    assert row["registered_by"] == "system:retro-register"
    assert row["embedding_model"] is None

    _reensure(db_conn)  # idempotent: the SQL guard, not just the memo no-op
    n = db_conn.execute("SELECT COUNT(*) AS n FROM rag_corpora").fetchone()
    assert n["n"] == 1
    assert (
        resolver.get_corpus(db_conn, domain_key="legal")["index_name"]
        == CUSTOM_DEFAULT_INDEX
    )


# =========================================================================== #
# resolve_index (task 3.1: 兼容 / 登记 / 未登记拒绝)                             #
# =========================================================================== #


def test_resolve_index_none_uses_live_default_setting(db_conn):
    """domain=None -> the global SEARCH_INDEX_NAME (byte-compat legacy path)."""
    assert resolver.resolve_index(db_conn, None) == CUSTOM_DEFAULT_INDEX


def test_resolve_index_legal_unregistered_falls_back_to_default(db_conn):
    """Unregistered legal predates the registry and keeps the default index."""
    assert resolver.resolve_index(db_conn, "legal") == CUSTOM_DEFAULT_INDEX


def test_resolve_index_legal_registered_row_wins_over_default(db_conn):
    """Once legal is registered, its row takes over from the default."""
    make_domain(db_conn, "legal")
    _reensure(db_conn)  # seed row carries the sentinel default
    assert resolver.resolve_index(db_conn, "legal") == CUSTOM_DEFAULT_INDEX

    # A later (prefix-exempt) re-registration takes over.
    resolver.register_corpus(
        db_conn, domain_key="legal", index_name="legal-retired",
        sources=[], registered_by="ops",
    )
    assert resolver.resolve_index(db_conn, "legal") == "legal-retired"


def test_resolve_index_registered_domain_returns_its_index(db_conn):
    """A registered non-legal domain resolves to its own registered index."""
    make_domain(db_conn, "fin")
    resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag",
        sources=[{"bucket": "b", "prefix": "p/"}], registered_by="ops",
    )
    assert resolver.resolve_index(db_conn, "fin") == "fin-rag"


def test_resolve_index_unregistered_domain_fails_closed_naming_domain(db_conn):
    """Fail closed: an existing-but-unregistered domain never falls back."""
    make_domain(db_conn, "fin")
    with pytest.raises(resolver.CorpusNotRegistered) as excinfo:
        resolver.resolve_index(db_conn, "fin")
    assert "fin" in str(excinfo.value)
    assert "register_corpus" in str(excinfo.value)  # honest remedy in message

    with pytest.raises(resolver.CorpusNotRegistered) as excinfo:
        resolver.resolve_index(db_conn, "ghost")  # domain doesn't even exist
    assert "ghost" in str(excinfo.value)


# =========================================================================== #
# register_corpus validations (task 3.1)                                       #
# =========================================================================== #


def test_register_corpus_requires_existing_domain(db_conn):
    """The domain must exist in ``domains`` — no phantom registrations."""
    with pytest.raises(ValueError, match="does not exist"):
        resolver.register_corpus(
            db_conn, domain_key="ghost", index_name="ghost-rag",
            sources=[], registered_by="ops",
        )
    assert resolver.get_corpus(db_conn, domain_key="ghost") is None


def test_register_corpus_enforces_index_prefix_for_non_legal(db_conn):
    """Index-name convention: ``{domain_key}-`` prefix, or refuse.

    Domain 'fin' pointed at 'legal-rag' would silently search another
    domain's corpus — exactly the cross-tenant mispoint the convention stops.
    """
    make_domain(db_conn, "fin")
    with pytest.raises(ValueError) as excinfo:
        resolver.register_corpus(
            db_conn, domain_key="fin", index_name="legal-rag",
            sources=[], registered_by="ops",
        )
    assert "must start with 'fin-'" in str(excinfo.value)
    assert resolver.get_corpus(db_conn, domain_key="fin") is None

    # The correct prefix registers fine.
    resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag",
        sources=[], registered_by="ops",
    )
    assert resolver.resolve_index(db_conn, "fin") == "fin-rag"


def test_register_corpus_legal_is_exempt_from_prefix_rule(db_conn):
    """The legal exemption: any index name (retro-registration compat)."""
    make_domain(db_conn, "legal")
    row = resolver.register_corpus(
        db_conn, domain_key="legal", index_name=CUSTOM_DEFAULT_INDEX,
        sources=[], registered_by="ops",
    )
    assert row["index_name"] == CUSTOM_DEFAULT_INDEX  # no 'legal-' prefix


@pytest.mark.parametrize(
    "bad_sources",
    [
        {"bucket": "b", "prefix": "p/"},  # not a list
        ["just-a-string"],  # element not a dict
        [{"prefix": "p/"}],  # missing bucket
        [{"bucket": "b"}],  # missing prefix
        [{"bucket": "   ", "prefix": "p/"}],  # blank bucket
        [{"bucket": "b", "prefix": ""}],  # blank prefix
    ],
    ids=["not-a-list", "element-not-dict", "missing-bucket", "missing-prefix",
         "blank-bucket", "blank-prefix"],
)
def test_register_corpus_rejects_bad_source_shapes(db_conn, bad_sources):
    """Sources must be [{bucket, prefix}] with non-empty strings; no partial
    row may survive a rejected registration."""
    make_domain(db_conn, "fin")
    with pytest.raises(ValueError):
        resolver.register_corpus(
            db_conn, domain_key="fin", index_name="fin-rag",
            sources=bad_sources, registered_by="ops",
        )
    assert resolver.get_corpus(db_conn, domain_key="fin") is None


def test_register_corpus_index_name_unique_across_domains(db_conn):
    """Two domains can never be pointed at one index.

    For non-legal domains the ``{domain_key}-`` prefix convention already
    refuses the mispoint (bio can never claim 'fin-rag'); the table-wide
    index_name UNIQUE is then the backstop that the prefix-exempt legal
    domain cannot bypass. Re-pointing one's OWN index stays allowed.
    """
    make_domain(db_conn, "fin")
    make_domain(db_conn, "bio")
    make_domain(db_conn, "legal")
    resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag",
        sources=[], registered_by="ops",
    )
    # bio fails at the prefix convention (a ValueError either way).
    with pytest.raises(ValueError):
        resolver.register_corpus(
            db_conn, domain_key="bio", index_name="fin-rag",
            sources=[], registered_by="ops",
        )
    # bio still has no row: the refusal rejected the whole registration.
    assert resolver.get_corpus(db_conn, domain_key="bio") is None

    # legal is prefix-exempt, so THIS one reaches the uniqueness backstop.
    with pytest.raises(ValueError, match="already registered to another domain"):
        resolver.register_corpus(
            db_conn, domain_key="legal", index_name="fin-rag",
            sources=[], registered_by="ops",
        )
    assert resolver.get_corpus(db_conn, domain_key="legal") is None

    # Same domain, different index: allowed (replace, not clash).
    resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag-v2",
        sources=[], registered_by="ops",
    )
    assert resolver.resolve_index(db_conn, "fin") == "fin-rag-v2"


def test_register_corpus_same_domain_reregister_replaces_row(db_conn):
    """Upsert-replace: re-registration rewrites the row, never duplicates it."""
    make_domain(db_conn, "fin")
    resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag",
        sources=[{"bucket": "old-b", "prefix": "old/"}], registered_by="first",
    )
    row = resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag-v2",
        sources=[{"bucket": "new-b", "prefix": "new/"}], registered_by="second",
    )
    assert row["index_name"] == "fin-rag-v2"
    assert row["registered_by"] == "second"

    stored = resolver.get_corpus(db_conn, domain_key="fin")
    assert stored["index_name"] == "fin-rag-v2"
    assert stored["sources"] == [{"bucket": "new-b", "prefix": "new/"}]  # replaced
    n = db_conn.execute(
        "SELECT COUNT(*) AS n FROM rag_corpora WHERE domain_id = %s",
        (row["domain_id"],),
    ).fetchone()
    assert n["n"] == 1  # single row per domain


def test_get_corpus_and_list_corpora_round_trip(db_conn):
    """Round-trip: fields survive the JSONB store; list is ordered by key."""
    make_domain(db_conn, "fin")
    make_domain(db_conn, "bio")
    resolver.register_corpus(
        db_conn, domain_key="bio", index_name="bio-rag",
        sources=[{"bucket": "bb", "prefix": "x/"}],
        registered_by="ops", embedding_model="emb-1",
    )
    resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag",
        sources=[], registered_by="ops2",
    )

    got = resolver.get_corpus(db_conn, domain_key="bio")
    assert got["domain_key"] == "bio"
    assert got["index_name"] == "bio-rag"
    assert got["sources"] == [{"bucket": "bb", "prefix": "x/"}]
    assert got["embedding_model"] == "emb-1"
    assert got["registered_by"] == "ops"
    assert got["created_at"]  # ISO-stringified timestamp

    assert [r["domain_key"] for r in resolver.list_corpora(db_conn)] == [
        "bio", "fin"  # ORDER BY d.key
    ]
    assert resolver.get_corpus(db_conn, domain_key="no-such") is None


# =========================================================================== #
# run_ingest resolution branches (task 3.2, kernel half — ES stubbed)          #
# =========================================================================== #


def test_ingest_unregistered_domain_fails_closed(db_conn):
    """No registry row -> CorpusNotRegistered naming the domain (both for an
    existing domain and a phantom one); nothing is loaded or written."""
    make_domain(db_conn, "fin")
    with pytest.raises(resolver.CorpusNotRegistered, match="'fin'"):
        ingest.run_ingest("fin", conn=db_conn)
    with pytest.raises(resolver.CorpusNotRegistered, match="'ghost'"):
        ingest.run_ingest("ghost", conn=db_conn)


def test_ingest_registered_domain_loads_each_source_into_its_index(
    db_conn, monkeypatch
):
    """Registered corpus: one load per declared {bucket, prefix}, in order,
    and the write lands on the REGISTERED index."""
    make_domain(db_conn, "fin")
    resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag",
        sources=[
            {"bucket": "bkt-a", "prefix": "pa/"},
            {"bucket": "bkt-b", "prefix": "pb/"},
        ],
        registered_by="ops",
    )
    stores, inserted = _stub_es_write(monkeypatch)
    load_calls = _stub_load(monkeypatch, with_docs=True)

    summary = ingest.run_ingest("fin", conn=db_conn)

    assert load_calls == [
        {"bucket": "bkt-a", "prefix": "pa/"},
        {"bucket": "bkt-b", "prefix": "pb/"},
    ]
    assert [s.index_name for s in stores] == ["fin-rag"]  # the registered index
    assert summary["documents"] == 2
    assert summary["errors"] == 0
    assert summary["chunks"] >= 1
    assert len(inserted) == summary["chunks"]


def test_ingest_prefix_argument_overrides_declared_prefixes(db_conn, monkeypatch):
    """An explicit ``prefix`` overrides every declared source prefix while the
    buckets still come from the registration."""
    make_domain(db_conn, "fin")
    resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag",
        sources=[
            {"bucket": "bkt-a", "prefix": "pa/"},
            {"bucket": "bkt-b", "prefix": "pb/"},
        ],
        registered_by="ops",
    )
    _stub_es_write(monkeypatch)
    load_calls = _stub_load(monkeypatch, with_docs=False)  # [] -> early honest return

    summary = ingest.run_ingest("fin", prefix="override/", conn=db_conn)

    assert load_calls == [
        {"bucket": "bkt-a", "prefix": "override/"},
        {"bucket": "bkt-b", "prefix": "override/"},
    ]
    assert summary == {"documents": 0, "chunks": 0, "errors": 0}


def test_ingest_legal_without_row_keeps_legacy_path(db_conn, monkeypatch):
    """Zero-migration legal: no registry row -> the pre-registry behavior.

    ``load_documents`` is called in its legacy single-positional-prefix shape
    (None = templates+drafts of the global MINIO_BUCKET, no bucket kwarg) and
    the write targets whichever index resolves for legal (the default here).
    """
    stores, inserted = _stub_es_write(monkeypatch)
    load_calls = _stub_load(monkeypatch, with_docs=True)

    summary = ingest.run_ingest("legal", conn=db_conn)

    assert load_calls == [{"bucket": None, "prefix": None}]
    assert [s.index_name for s in stores] == [CUSTOM_DEFAULT_INDEX]
    assert summary["documents"] == 1
    assert summary["chunks"] >= 1 and summary["errors"] == 0
    assert len(inserted) == summary["chunks"]

    # An explicit prefix rides the same legacy call shape.
    load_calls.clear()
    stores.clear()
    inserted.clear()
    ingest.run_ingest("legal", prefix="legal-extra/", conn=db_conn)
    assert load_calls == [{"bucket": None, "prefix": "legal-extra/"}]


def test_ingest_registered_without_sources_is_honest_noop(db_conn, monkeypatch):
    """Registered but zero sources: searchable-not-ingestible corpus reports
    zeros honestly — no load call, no ES touch, no error."""
    make_domain(db_conn, "fin")
    resolver.register_corpus(
        db_conn, domain_key="fin", index_name="fin-rag",
        sources=[], registered_by="ops",
    )
    stores, _inserted = _stub_es_write(monkeypatch)
    load_calls = _stub_load(monkeypatch, with_docs=False)

    summary = ingest.run_ingest("fin", conn=db_conn)

    assert summary == {"documents": 0, "chunks": 0, "errors": 0}
    assert load_calls == []
    assert stores == []
