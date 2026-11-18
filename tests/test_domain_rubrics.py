"""Domain-scoped evaluation standards (§3.4 / §3.5).

Pins the two rules that make inheritance safe rather than merely convenient:

- effective resolution picks the **nearest** definition per rubric name, and
  reports whether it is the domain's own or inherited (a child that silently
  inherits a changed parent standard is the failure mode we are guarding);
- a fork without a written difference summary is refused — a silent copy is
  indistinguishable from its parent forever, which is exactly what an
  evaluation standard must never be.
"""

from __future__ import annotations

import pytest

from src.bench import domain_rubrics, templates
from src.eval import store as eval_store
from src.bench.tiers import TIERS
from src.bench.promotion import SENSITIVITY_LEVELS
from src.eval.store import ensure_schema


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    # rubrics/criteria are created by a legacy seed script, not by ensure_schema,
    # so a fresh per-test database has neither. Recreate the production shapes
    # here, then re-run ensure_schema so its guarded backfill (domain_id) lands.
    empty_db.execute(
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
    empty_db.execute(
        """
        CREATE TABLE IF NOT EXISTS criteria (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            rubric_id BIGINT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            guidance TEXT,
            ordinal INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    empty_db.commit()
    eval_store._ensured_dbs.clear()
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


def _domains(conn):
    templates.create_template(conn, name="tpl", schema=_schema(), created_by="t")
    tid = conn.execute("SELECT id FROM ontology_templates LIMIT 1").fetchone()["id"]
    root = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "VALUES ('legal','Legal',%s,1,'t','legal') RETURNING id, path",
        (tid,),
    ).fetchone()
    child = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
        "VALUES ('cr','CR',%s,1,'t',%s,'legal/cr') RETURNING id, path",
        (tid, root["id"]),
    ).fetchone()
    sibling = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
        "VALUES ('lp','LP',%s,1,'t',%s,'legal/lp') RETURNING id, path",
        (tid, root["id"]),
    ).fetchone()
    conn.commit()
    return dict(root), dict(child), dict(sibling)


def _criteria(*names):
    return [{"name": n, "description": f"d-{n}", "guidance": f"g-{n}"} for n in names]


def test_child_sees_parent_rubric_as_inherited(conn):
    root, child, _ = _domains(conn)
    domain_rubrics.create_for_domain(
        conn, domain_id=root["id"], name="contract_quality", context="check",
        criteria=_criteria("completeness", "risk"),
    )
    items = domain_rubrics.effective_rubrics(conn, domain_path=child["path"])
    assert [i["name"] for i in items] == ["contract_quality"]
    assert items[0]["origin"] == "inherited"
    assert items[0]["domain_id"] == root["id"]


def test_own_rubric_shadows_parent_by_name(conn):
    root, child, _ = _domains(conn)
    domain_rubrics.create_for_domain(
        conn, domain_id=root["id"], name="quality", context="check", criteria=_criteria("a")
    )
    domain_rubrics.create_for_domain(
        conn, domain_id=child["id"], name="quality", context="check", criteria=_criteria("a", "b")
    )
    items = domain_rubrics.effective_rubrics(conn, domain_path=child["path"])
    assert len(items) == 1, "same name must resolve to a single standard"
    assert items[0]["origin"] == "own"
    detail = domain_rubrics.get_effective(conn, domain_path=child["path"], name="quality")
    assert [c["name"] for c in detail["criteria"]] == ["a", "b"]


def test_sibling_rubrics_are_invisible(conn):
    root, child, sibling = _domains(conn)
    domain_rubrics.create_for_domain(
        conn, domain_id=sibling["id"], name="lp_only", context="check", criteria=_criteria("x")
    )
    assert domain_rubrics.effective_rubrics(conn, domain_path=child["path"]) == []


def test_fork_requires_a_diff(conn):
    root, child, _ = _domains(conn)
    src = domain_rubrics.create_for_domain(
        conn, domain_id=root["id"], name="quality", context="check", criteria=_criteria("a")
    )
    with pytest.raises(domain_rubrics.ForkError):
        domain_rubrics.fork(conn, source_rubric_id=src["id"], domain_id=child["id"], fork_diff={})


def test_fork_records_parent_and_diff(conn):
    root, child, _ = _domains(conn)
    src = domain_rubrics.create_for_domain(
        conn, domain_id=root["id"], name="quality", context="check",
        criteria=_criteria("completeness", "risk"),
    )
    forked = domain_rubrics.fork(
        conn,
        source_rubric_id=src["id"],
        domain_id=child["id"],
        fork_diff={"criteria": {"risk": "提高阈值到 0.9"}},
    )
    assert forked["derived_from"] == src["id"]
    assert forked["fork_diff"]["criteria"]["risk"].startswith("提高阈值")
    # The fork is now the child's own standard, shadowing the parent.
    items = domain_rubrics.effective_rubrics(conn, domain_path=child["path"])
    assert items[0]["origin"] == "own"


def test_run_attribution_and_domain_history(conn):
    root, child, sibling = _domains(conn)
    parent_rubric = domain_rubrics.create_for_domain(
        conn, domain_id=root["id"], name="quality", context="check", criteria=_criteria("a")
    )
    sibling_rubric = domain_rubrics.create_for_domain(
        conn, domain_id=sibling["id"], name="lp", context="check", criteria=_criteria("b")
    )
    for rubric, name in ((parent_rubric, "quality"), (sibling_rubric, "lp")):
        conn.execute(
            "INSERT INTO eval_runs (rubric_name, score, max_score, n_criteria, n_passed, "
            "all_pass, scored_at, created_at) "
            "VALUES (%s, 1, 2, 2, 1, 0, 'now', 'now') RETURNING id",
            (name,),
        )
    ids = [r["id"] for r in conn.execute("SELECT id FROM eval_runs ORDER BY id").fetchall()]
    conn.commit()
    domain_rubrics.attribute_run(conn, run_id=ids[0], rubric_id=parent_rubric["id"])
    domain_rubrics.attribute_run(conn, run_id=ids[1], rubric_id=sibling_rubric["id"])

    child_runs = domain_rubrics.runs_for_domain(conn, domain_path=child["path"])
    assert [r["rubric_name"] for r in child_runs] == ["quality"], (
        "a child inherits the parent's run history, not the sibling's"
    )
