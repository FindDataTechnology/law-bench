"""Template readiness gate (change add-layered-ontology-templates, task 3-4).

``rubric_refs`` used to be prose: nothing read it, so "this template is judged by
these rulers" could never be wrong. These tests pin what replaced it — refs
resolve against the domain's *effective* ruler set, and a new template version
cannot be worse than the last verdict.

The three-outcome case matters most: ``inconclusive`` means "could not tell", and
the whole point of the ledger's third state is that it must never be read as
"did not fail".
"""

from __future__ import annotations

import pytest

from src.bench import template_readiness, templates
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    # rubrics comes from a legacy seed script, not ensure_schema; readiness
    # resolution reads it, so recreate the deployed shape (the same shim
    # tests/test_estate_matrix.py uses).
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


@pytest.fixture()
def domain(db_conn):
    """A domain whose template declares no rulers, plus one usable rubric."""
    tpl = templates.create_template(
        db_conn, name="readiness-tpl", schema=schema(), created_by="t"
    )
    db_conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "VALUES ('d','D',%s,1,'t','d')",
        (tpl["id"],),
    )
    db_conn.execute(
        "INSERT INTO rubrics (name, context, source, description, domain_id) "
        "VALUES ('alpha','ctx','seed','d',(SELECT id FROM domains WHERE key='d'))"
    )
    db_conn.commit()
    return "d"


def schema(**over) -> dict:
    base = {
        "entity_types": ["organization"],
        "concept_structures": {},
        "relationship_kinds": ["part_of"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": []},
        "layer": "industry",
    }
    base.update(over)
    return base


# --------------------------------------------------------------- resolution


def test_no_declared_rulers_reports_none_not_zero(db_conn, domain):
    report = template_readiness.readiness(db_conn, domain_path=domain, schema=schema())
    assert report["declared"] == 0
    assert report["rate"] is None, (
        "an empty denominator rendered as 0.0 or 1.0 reads as a percentage; "
        "the page must be able to say 'not measurable'"
    )
    assert report["digest"] is None


def test_partially_resolved_reports_the_rate_and_the_missing_one(db_conn, domain):
    report = template_readiness.readiness(
        db_conn, domain_path=domain, schema=schema(rubric_refs=["alpha", "ghost"])
    )
    assert report["declared"] == 2
    assert report["resolved"] == 1
    assert report["missing"] == ["ghost"]
    assert report["rate"] == 0.5


def test_fully_resolved(db_conn, domain):
    report = template_readiness.readiness(
        db_conn, domain_path=domain, schema=schema(rubric_refs=["alpha"])
    )
    assert report["rate"] == 1.0 and report["missing"] == []


def test_digest_ignores_order_and_duplicates():
    a = template_readiness.rubric_digest(schema(rubric_refs=["a", "b"]))
    b = template_readiness.rubric_digest(schema(rubric_refs=["b", "a", "a"]))
    assert a == b, "the same ruler set must digest the same way"


def test_digest_changes_when_the_ruler_set_changes():
    a = template_readiness.rubric_digest(schema(rubric_refs=["a"]))
    b = template_readiness.rubric_digest(schema(rubric_refs=["a", "b"]))
    assert a != b


# ------------------------------------------------------------ instantiation


def test_instance_problem_names_the_unresolvable_ruler(db_conn, domain):
    problem = template_readiness.instance_problem(
        db_conn, domain_path=domain, schema=schema(rubric_refs=["ghost"])
    )
    assert problem is not None and "ghost" in problem


def test_instance_problem_for_empty_rulers_says_why(db_conn, domain):
    problem = template_readiness.instance_problem(
        db_conn, domain_path=domain, schema=schema()
    )
    assert problem is not None
    assert "rubric_refs" in problem


def test_instance_problem_is_none_when_everything_resolves(db_conn, domain):
    assert template_readiness.instance_problem(
        db_conn, domain_path=domain, schema=schema(rubric_refs=["alpha"])
    ) is None


# ----------------------------------------------------------- promotion gate


def _seed_verdict(db_conn, *, outcome: str, ruler_digest: str = "d1") -> None:
    """Write one ledger row for the template subject through the real write path.

    Going through ``store_result`` rather than a hand-written INSERT is what makes
    this test worth having: the ledger's own writer validates the identity fields,
    so a hand-written row could prove the gate reads a shape the real path never
    produces.
    """
    from src.eval.store import store_result

    store_result(
        {
            "rubric": "r", "score": 0.5, "max_score": 1.0,
            "all_pass": outcome == "pass",
            "n_criteria": 1, "n_passed": 1 if outcome == "pass" else 0,
            "summary": "seed", "judge_model": "deterministic",
            "criteria_results": [
                {"id": "c1", "title": "t", "verdict": "pass", "reasoning": "ok"}
            ],
        },
        db_path=db_conn,
        subject_kind="template", subject_key="tpl", subject_version="v1",
        ruler_kind="rubric", ruler_key="alpha", ruler_digest=ruler_digest,
        gate="no-worse", outcome=outcome,
    )


def test_first_version_is_always_allowed(db_conn):
    created = template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(), created_by="t"
    )
    assert created["version"] == 1


def test_no_comparable_history_is_a_baseline_not_a_regression(db_conn):
    template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(), created_by="t"
    )
    created = template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
    )
    assert created["version"] == 2


def test_failing_verdict_blocks_the_promotion(db_conn):
    template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
    )
    digest = template_readiness.rubric_digest(schema(rubric_refs=["alpha"]))
    _seed_verdict(db_conn, outcome="fail", ruler_digest=digest)

    with pytest.raises(ValueError) as exc:
        template_readiness.promote_template_via_gate(
            db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
        )
    assert "变差" in str(exc.value)
    # The rejected version did not land.
    assert templates.get_template(db_conn, name="tpl")["version"] == 1


def test_inconclusive_must_not_be_read_as_pass(db_conn):
    template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
    )
    digest = template_readiness.rubric_digest(schema(rubric_refs=["alpha"]))
    _seed_verdict(db_conn, outcome="inconclusive", ruler_digest=digest)

    with pytest.raises(ValueError) as exc:
        template_readiness.promote_template_via_gate(
            db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
        )
    assert "判不出来" in str(exc.value)


def test_passing_verdict_lets_it_through(db_conn):
    template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
    )
    digest = template_readiness.rubric_digest(schema(rubric_refs=["alpha"]))
    _seed_verdict(db_conn, outcome="pass", ruler_digest=digest)

    created = template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
    )
    assert created["version"] == 2


def test_a_moved_measuring_stick_re_baselines(db_conn):
    """Different ruler digest = new baseline, never a comparison against old scores."""
    template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
    )
    _seed_verdict(db_conn, outcome="fail", ruler_digest="some-other-digest")

    created = template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
    )
    assert created["version"] == 2


def test_dropping_the_rulers_is_itself_a_regression(db_conn):
    """Otherwise 'delete rubric_refs, then promote' is the way around the gate."""
    template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(rubric_refs=["alpha"]), created_by="t"
    )
    with pytest.raises(ValueError) as exc:
        template_readiness.promote_template_via_gate(
            db_conn, name="tpl", schema=schema(), created_by="t"
        )
    assert "删掉" in str(exc.value)
    assert templates.get_template(db_conn, name="tpl")["version"] == 1


def test_neither_version_declaring_rulers_is_not_a_gate(db_conn):
    """Save-time is deliberately permissive so a template can be built in steps."""
    template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(), created_by="t"
    )
    created = template_readiness.promote_template_via_gate(
        db_conn, name="tpl", schema=schema(relationship_kinds=["part_of"]), created_by="t"
    )
    assert created["version"] == 2
