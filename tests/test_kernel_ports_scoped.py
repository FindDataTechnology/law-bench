"""Ports resolve one domain per ``scope_id`` (add-law-bench-conformance-adapter 1.2).

The conformance suite needs one kernel to serve many scopes (``scope-a``,
``scope-fold``, …), while production has always bound a kernel to one domain.
The ports therefore resolve the domain **per call** instead of pinning it in the
constructor — this file pins the two consequences that refactor could get wrong:

- two scopes on one connection keep separate vocabularies (no crossing), and a
  write in one scope is invisible to the other;
- production still refuses an unknown scope: ``mint`` is a sandbox-only escape
  hatch, so a typoed domain key stays an error instead of silently becoming a
  new domain.

The classification assertions come from the real template row, not from a
hardcoded tuple, so a template edit is visible here too.
"""

from __future__ import annotations

import pytest

from src.bench import kernel_ports, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


def _schema(entity_types: list[str], relationship_kinds: list[str]) -> dict:
    return {
        "entity_types": entity_types,
        "concept_structures": {},
        "relationship_kinds": relationship_kinds,
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": []},
    }


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    yield empty_db
    from src.eval.db import close_shared_conn

    close_shared_conn()


def _domain(conn, *, template: str, key: str, entity_types: list[str]) -> dict:
    templates.create_template(
        conn=conn,
        name=template,
        schema=_schema(entity_types, ["belongs_to"]),
        created_by="t",
    )
    return workspaces.instantiate_domain(
        conn=conn,
        key=key,
        name=key,
        template_name=template,
        template_version=None,
        created_by="t",
    )


def test_two_scopes_keep_separate_vocabularies_and_rows(conn):
    left = _domain(conn, template="tpl-left", key="scope-left", entity_types=["company"])
    conn.commit()

    kernel = kernel_ports.kernel_for(conn, domain=left)

    # A second scope appears after the kernel was built: per-call resolution is
    # what makes this visible at all. A constructor-pinned kernel would either
    # raise or (worse) write into the first scope.
    _domain(conn, template="tpl-right", key="scope-right", entity_types=["indicator"])
    conn.commit()

    assert kernel.vocabulary_for("scope-left").set("entity_types").values == ("company",)
    assert kernel.vocabulary_for("scope-right").set("entity_types").values == ("indicator",)

    kernel.write(
        scope_id="scope-left", kind="company", external_key="k", body="b", actor="t"
    )
    conn.commit()

    assert kernel.units.get(scope_id="scope-left", kind="company", external_key="k")
    assert kernel.units.get(scope_id="scope-right", kind="company", external_key="k") is None
    assert kernel.units.list_live(scope_id="scope-right") == []


def test_unknown_scope_is_an_error_without_mint(conn):
    seed = _domain(conn, template="tpl-seed", key="scope-seed", entity_types=["company"])
    conn.commit()

    kernel = kernel_ports.kernel_for(conn, domain=seed)

    # Reads are tolerant on purpose ("this scope has nothing" is the truth)…
    assert kernel.events.fold(scope_id="scope-typo") == []
    # …but a write must not invent a domain from a typo.
    with pytest.raises(ValueError, match="unknown scope"):
        kernel.write(
            scope_id="scope-typo", kind="company", external_key="k", body="b", actor="t"
        )


def test_mint_creates_the_domain_on_first_use(conn):
    seed = _domain(conn, template="tpl-mint-seed", key="scope-mint-seed",
                   entity_types=["company"])
    conn.commit()

    minted: list[str] = []

    def mint(scope_id: str) -> dict:
        minted.append(scope_id)
        domain = _domain(
            conn,
            template=f"tpl-{scope_id}",
            key=scope_id,
            entity_types=["clause"],
        )
        conn.commit()
        return domain

    kernel = kernel_ports.kernel_for(conn, domain=seed, mint=mint)

    kernel.write(scope_id="scope-mint", kind="clause", external_key="k", body="b",
                 actor="t")
    conn.commit()

    assert minted == ["scope-mint"]
    assert kernel.vocabulary_for("scope-mint").set("entity_types").values == ("clause",)
    # The seed domain is untouched by the mint.
    assert kernel.vocabulary_for("scope-mint-seed").set("entity_types").values == ("company",)
