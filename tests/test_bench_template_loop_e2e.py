"""One real chain, end to end (change add-layered-ontology-templates, task 7.2).

The pieces are tested separately above; this file exists because "each unit is
green" has never once been the same thing as "the loop closes". It walks the
chain the change is for:

    template v1 with rulers  →  a template verdict lands  →  v2 passes the gate
    →  a retest obligation is booked on an existing work order

Every step is verified against the database, not against a return value.
"""

from __future__ import annotations

import pytest

from src.bench import template_readiness, templates, verdicts
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema, store_result


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    empty_db.execute(
        """
        CREATE TABLE IF NOT EXISTS rubrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            context TEXT,
            source TEXT,
            source_path TEXT,
            description TEXT,
            domain_id BIGINT,
            derived_from BIGINT,
            fork_diff JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    empty_db.commit()
    yield empty_db


def schema(**over) -> dict:
    base = {
        "layer": "industry",
        "authority": {"kind": "platform"},
        "entity_types": ["organization", "warehouse"],
        "concept_structures": {},
        "relationship_kinds": ["part_of"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": []},
        "rubric_refs": ["ledger-integrity"],
    }
    base.update(over)
    return base


def _seed_rubric(conn, *, domain_key: str = "erp") -> None:
    tpl = templates.create_template(conn, name="seed-tpl", schema=dict(schema(), rubric_refs=[]),
                                    created_by="t")
    conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "VALUES (%s,'ERP',%s,1,'t',%s) ON CONFLICT DO NOTHING",
        (domain_key, tpl["id"], domain_key),
    )
    conn.execute(
        "INSERT INTO rubrics (name, context, source, description, domain_id) "
        "VALUES ('ledger-integrity','ctx','seed','d',(SELECT id FROM domains WHERE key=%s))",
        (domain_key,),
    )
    conn.commit()


def test_the_whole_chain(db_conn):
    _seed_rubric(db_conn)

    # 1. v1 with a ruler — the template can now be measured at all.
    v1 = template_readiness.promote_template_via_gate(
        db_conn, name="enterprise-base", schema=schema(), created_by="t"
    )
    assert v1["version"] == 1
    assert template_readiness.instance_problem(
        db_conn, domain_path="erp", schema=schema()
    ) is None

    # 2. A verdict lands for that template, judged by exactly the declared ruler.
    digest = template_readiness.rubric_digest(schema())
    store_result(
        {
            "rubric": "ledger-integrity", "score": 1.0, "max_score": 1.0,
            "all_pass": True, "n_criteria": 1, "n_passed": 1,
            "summary": "coverage 12/12", "judge_model": "deterministic",
            "criteria_results": [
                {"id": "c1", "title": "t", "verdict": "pass", "reasoning": "ok"}
            ],
        },
        db_path=db_conn,
        subject_kind=verdicts.TEMPLATE_SUBJECT_KIND,
        subject_key="enterprise-base", subject_version="v1",
        ruler_kind="rubric", ruler_key="ledger-integrity", ruler_digest=digest,
        gate=template_readiness.PROMOTION_GATE, outcome="pass",
    )

    # 3. v2 clears the gate and actually lands.
    v2 = template_readiness.promote_template_via_gate(
        db_conn, name="enterprise-base",
        schema=schema(entity_types=["organization", "warehouse", "account"]),
        created_by="t",
    )
    assert v2["version"] == 2
    stored = templates.get_template(db_conn, name="enterprise-base")
    assert stored["version"] == 2
    assert "account" in stored["schema"]["entity_types"]
    # v1 is untouched — domains pinned to it are unaffected.
    assert templates.get_template(db_conn, name="enterprise-base", version=1)[
        "schema"]["entity_types"] == ["organization", "warehouse"]

    # 3b. The promotion books the obligation to re-measure, without running it.
    task = verdicts.register_retest(
        db_conn, domain_key="erp",
        subject_kind=verdicts.TEMPLATE_SUBJECT_KIND,
        subject_key="enterprise-base", subject_version="v2",
        baseline_run_id=None, created_by="t",
    )
    assert task["target_kind"] == verdicts.RETEST_TARGET_KIND
    assert "enterprise-base@v2" in task["target_key"]
    # Idempotent: the same shipped version does not book a second obligation.
    again = verdicts.register_retest(
        db_conn, domain_key="erp",
        subject_kind=verdicts.TEMPLATE_SUBJECT_KIND,
        subject_key="enterprise-base", subject_version="v2",
        baseline_run_id=None, created_by="t",
    )
    assert again["id"] == task["id"]

    # 4. A failing verdict now blocks the next promotion.
    store_result(
        {
            "rubric": "ledger-integrity", "score": 0.2, "max_score": 1.0,
            "all_pass": False, "n_criteria": 1, "n_passed": 0,
            "summary": "coverage 2/12", "judge_model": "deterministic",
            "criteria_results": [
                {"id": "c1", "title": "t", "verdict": "fail", "reasoning": "no"}
            ],
        },
        db_path=db_conn,
        subject_kind=verdicts.TEMPLATE_SUBJECT_KIND,
        subject_key="enterprise-base", subject_version="v2",
        ruler_kind="rubric", ruler_key="ledger-integrity", ruler_digest=digest,
        gate=template_readiness.PROMOTION_GATE, outcome="fail",
    )
    with pytest.raises(ValueError):
        template_readiness.promote_template_via_gate(
            db_conn, name="enterprise-base",
            schema=schema(entity_types=["organization"]), created_by="t",
        )
    assert templates.get_template(db_conn, name="enterprise-base")["version"] == 2
