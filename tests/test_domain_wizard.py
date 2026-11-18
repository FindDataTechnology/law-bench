"""Sub-domain wizard (§4.6).

The wizard's value is that it cannot produce a domain whose scope retrieval
would then reject, and that it refuses to *guess* a parent. Both are checked
here against the real store rather than the rendered HTML:

- creating with a parent composes the materialized path;
- a missing parent is refused (a typo must not detach a sub-domain);
- the wizard's subscription selection is validated by the same resolver search
  uses, so selecting a source the parent never granted fails loudly at creation.
"""

from __future__ import annotations

import pytest

from src.bench import libraries, templates, workspaces
from src.bench.tiers import TIERS
from src.bench.promotion import SENSITIVITY_LEVELS
from src.eval import store as eval_store
from src.eval.store import ensure_schema
from src.search import library_index


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    yield empty_db


def _schema() -> dict:
    return {
        "entity_types": ["clause"],
        "concept_structures": {"clause": ["id"]},
        "relationship_kinds": ["cites_law"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": ["uploaded"]},
    }


def _root(conn) -> dict:
    templates.create_template(conn, name="tpl", schema=_schema(), created_by="t")
    return workspaces.instantiate_domain(
        conn, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )


def test_root_domain_gets_its_key_as_path(conn):
    root = _root(conn)
    assert root["path"] == "legal"


def test_child_composes_parent_path(conn):
    _root(conn)
    child = workspaces.instantiate_domain(
        conn, key="contract-review", name="合同审查", template_name="tpl",
        template_version=None, created_by="t", parent_key="legal",
    )
    assert child["path"] == "legal/contract-review"


def test_missing_parent_is_refused(conn):
    _root(conn)
    with pytest.raises(ValueError, match="parent domain"):
        workspaces.instantiate_domain(
            conn, key="orphan", name="Orphan", template_name="tpl",
            template_version=None, created_by="t", parent_key="ghost",
        )
    assert conn.execute("SELECT COUNT(*) AS n FROM domains WHERE key='orphan'").fetchone()["n"] == 0


def test_wizard_subscription_selection_must_stay_within_parent(conn):
    root = _root(conn)
    libraries.create_library(conn, library_key="law", name="法规库", created_by="t")
    for key in ("statutes", "contracts"):
        libraries.add_source(conn, library_key="law", source_key=key, uri=f"s3://b/{key}", created_by="t")
    # The parent grants only "statutes".
    libraries.subscribe(
        conn, domain_id=root["id"], library_key="law", created_by="t", source_filter=["statutes"]
    )
    child = workspaces.instantiate_domain(
        conn, key="cr", name="合同审查", template_name="tpl",
        template_version=None, created_by="t", parent_key="legal",
    )
    # A wizard selection that widens is rejected by the same resolver retrieval
    # uses — the exact call the create route makes before declaring success.
    libraries.subscribe(
        conn, domain_id=child["id"], library_key="law", created_by="t",
        source_filter=["statutes", "contracts"],
    )
    with pytest.raises(ValueError, match="widen"):
        library_index.explain_scope(conn, domain_path=child["path"])


def test_inherited_vocabulary_preview_matches_effective_schema(conn):
    from src.bench import inheritance

    _root(conn)
    parent = workspaces.get_domain(conn, domain_key="legal")
    tmpl = templates.get_template_by_id(conn, template_id=parent["template_id"])
    child_schema = {**_schema(), "entity_types": ["clause", "claim"],
                    "extends": {"name": tmpl["name"], "version": tmpl["version"]}}
    effective = inheritance.resolve_template_schema(conn, child_schema)
    # The wizard shows exactly this list, so the preview cannot promise
    # vocabulary the instance would not actually get.
    assert effective["entity_types"] == ["clause", "claim"]
