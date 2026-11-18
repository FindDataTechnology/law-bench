"""Run-ledger ↔ verdict-ledger interlink (add-eval-verdict-ledger 4.x).

Both directions, against the real DB: a round points at the verdicts it produced,
a verdict points back at the round. The failure these guard against is a read面
that "fills in" the missing link with the nearest row — attaching evidence to the
wrong work is worse than showing none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.bench import agent_ids, agent_runs, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema, store_result


@pytest.fixture()
def domain_key(empty_db):
    """One template + one domain, so ``agent_runs.start``'s domain check passes."""
    ensure_schema(db_path=empty_db)
    tmpl = templates.create_template(
        empty_db,
        name="tpl-interlink",
        schema={
            "entity_types": ["company"],
            "concept_structures": {},
            "relationship_kinds": ["belongs_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {},
        },
        created_by="admin-1",
    )
    domain = workspaces.instantiate_domain(
        empty_db,
        key="interlink",
        name="Interlink",
        template_name=tmpl["name"],
        template_version=tmpl["version"],
        created_by="admin-1",
    )
    return domain["key"]


@pytest.fixture()
def role() -> str:
    return agent_ids.agent_identity("builder", "interlink")


def _verdict(db, rubric: str = "l_rubric") -> int:
    return store_result(
        {
            "rubric": rubric, "score": 0.0, "max_score": 1.0, "all_pass": False,
            "n_criteria": 1, "n_passed": 0, "summary": "s",
            "judge_model": "fake", "criteria_results": [],
        },
        db_path=db,
    )


def test_run_points_at_its_verdicts_and_back(empty_db, domain_key: str, role: str):
    v1, v2 = _verdict(empty_db), _verdict(empty_db)
    run = agent_runs.start(
        empty_db, role=role, domain_key=domain_key
    )
    finished = agent_runs.finish(
        empty_db, run_id=run["id"], outcome="ok", verdict_run_ids=[v1, v2]
    )
    assert finished["verdict_run_ids"] == sorted([v1, v2]) or len(finished["verdict_run_ids"]) == 2

    produced = agent_runs.verdicts_for_run(empty_db, run_id=run["id"])
    assert {row["id"] for row in produced} == {v1, v2}

    back = agent_runs.run_for_verdict(empty_db, verdict_run_id=v1)
    assert back is not None and back["id"] == run["id"]


def test_run_without_verdicts_links_nothing(empty_db, domain_key: str, role: str):
    run = agent_runs.start(
        empty_db, role=role, domain_key=domain_key
    )
    finished = agent_runs.finish(empty_db, run_id=run["id"], outcome="ok")
    assert finished["verdict_run_ids"] == []
    assert agent_runs.verdicts_for_run(empty_db, run_id=run["id"]) == []


def test_verdict_from_a_non_round_has_no_run(empty_db):
    """A CLI one-shot has no round; the reverse lookup must say so, not guess."""
    v = _verdict(empty_db)
    assert agent_runs.run_for_verdict(empty_db, verdict_run_id=v) is None


def test_missing_verdict_row_is_omitted_not_faked(empty_db, domain_key: str, role: str):
    run = agent_runs.start(
        empty_db, role=role, domain_key=domain_key
    )
    agent_runs.finish(
        empty_db, run_id=run["id"], outcome="ok", verdict_run_ids=[999_999_999]
    )
    assert agent_runs.verdicts_for_run(empty_db, run_id=run["id"]) == []


def test_finish_is_idempotent_and_keeps_the_first_links(
    empty_db, domain_key: str, role: str
):
    v1 = _verdict(empty_db)
    run = agent_runs.start(
        empty_db, role=role, domain_key=domain_key
    )
    agent_runs.finish(
        empty_db, run_id=run["id"], outcome="ok", verdict_run_ids=[v1]
    )
    again = agent_runs.finish(
        empty_db, run_id=run["id"], outcome="failed", verdict_run_ids=[]
    )
    assert again["outcome"] == "ok"  # 已收尾不改写
    assert again["verdict_run_ids"] == [v1]


# --- 5.x retest obligation ------------------------------------------------


def test_promotion_books_a_retest_with_the_baseline(empty_db, domain_key: str):
    from src.bench import verdicts

    task = verdicts.register_retest(
        empty_db,
        domain_key=domain_key,
        subject_kind="pack",
        subject_key="ontology-builder",
        subject_version="v4",
        baseline_run_id=_verdict(empty_db),
        created_by="owner@example.com",
    )
    assert task["target_kind"] == verdicts.RETEST_TARGET_KIND
    assert task["status"] == "pending"
    assert "ontology-builder@v4" in task["target_key"] or "ontology-builder@v4" in task["title"]


def test_retest_is_registered_not_executed(empty_db, domain_key: str):
    """Booking a retest must not produce a verdict — evaluation costs money."""
    from src.bench import verdicts

    before = empty_db.execute("SELECT COUNT(*) AS n FROM eval_runs").fetchone()["n"]
    verdicts.register_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p",
        subject_version="v1", baseline_run_id=None, created_by="o@e.com",
    )
    after = empty_db.execute("SELECT COUNT(*) AS n FROM eval_runs").fetchone()["n"]
    assert after == before


def test_same_version_does_not_book_twice_new_version_does(empty_db, domain_key: str):
    from src.bench import verdicts

    a = verdicts.register_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p",
        subject_version="v1", baseline_run_id=None, created_by="o@e.com",
    )
    b = verdicts.register_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p",
        subject_version="v1", baseline_run_id=None, created_by="o@e.com",
    )
    c = verdicts.register_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p",
        subject_version="v2", baseline_run_id=None, created_by="o@e.com",
    )
    assert a["id"] == b["id"]
    assert c["id"] != a["id"]


def test_no_baseline_is_stated_not_faked(empty_db, domain_key: str):
    from src.bench import verdicts

    task = verdicts.register_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p",
        subject_version="v1", baseline_run_id=None, created_by="o@e.com",
    )
    assert "立基线" in (task["detail"] or "")
    assert "不构成进步证据" in (task["detail"] or "")


def test_unknown_domain_raises(empty_db, domain_key: str):
    from src.bench import verdicts

    with pytest.raises(ValueError):
        verdicts.register_retest(
            empty_db, domain_key="nope", subject_kind="pack", subject_key="p",
            subject_version="v1", baseline_run_id=None, created_by="o@e.com",
        )


# --- 5.2 retest cites the promotion-time baseline --------------------------


def test_retest_reads_back_the_baseline_it_was_booked_with(empty_db, domain_key: str):
    from src.bench import verdicts

    base = _verdict(empty_db)
    verdicts.register_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p",
        subject_version="v2", baseline_run_id=base, created_by="o@e.com",
    )
    assert verdicts.baseline_for_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p"
    ) == base


def test_retest_without_recorded_baseline_reads_as_none(empty_db, domain_key: str):
    from src.bench import verdicts

    verdicts.register_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p",
        subject_version="v2", baseline_run_id=None, created_by="o@e.com",
    )
    assert verdicts.baseline_for_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p"
    ) is None


def test_done_retest_is_history_not_a_pending_candidate(empty_db, domain_key: str):
    from src.bench import verdicts

    task = verdicts.register_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p",
        subject_version="v2", baseline_run_id=_verdict(empty_db), created_by="o@e.com",
    )
    empty_db.execute(
        "UPDATE authoring_tasks SET status = 'done' WHERE id = %s", (task["id"],)
    )
    empty_db.commit()
    assert verdicts.find_open_retest(
        empty_db, domain_key=domain_key, subject_kind="pack", subject_key="p"
    ) is None
