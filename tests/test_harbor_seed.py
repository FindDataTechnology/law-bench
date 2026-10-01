"""Tests for ``src.eval.harbor_seed`` - bundled-seed self-heal of harbor rubrics.

These simulate the container: harbor is treated as not installed
(``find_harbor_package`` -> ``None``) so the heal loads from the bundled seed
pinned to ``harbor:v0.20.0``, making the tests hermetic and version-independent.
"""

from __future__ import annotations

import pytest

from src.eval import harbor_seed
from src.eval import store


@pytest.fixture
def bundled_mode(monkeypatch) -> None:
    """Force the bundled-seed fallback (simulate harbor not installed)."""
    monkeypatch.setattr(harbor_seed, "find_harbor_package", lambda: None)


def test_ensure_heals_empty_db(empty_db, bundled_mode) -> None:
    summary = harbor_seed.ensure_harbor_rubrics(empty_db)

    assert summary["rubrics"] == 2
    assert summary["criteria"] == 13
    assert summary["source_origin"] == "bundled"
    rows = empty_db.execute(
        "SELECT name, source, context FROM rubrics WHERE source LIKE 'harbor:%%' "
        "ORDER BY name"
    ).fetchall()
    assert [r["name"] for r in rows] == ["task_quality", "trial_behavior"]
    assert all(r["source"] == "harbor:v0.20.0" for r in rows)
    assert empty_db.execute("SELECT COUNT(*) AS n FROM criteria").fetchone()["n"] == 13


def test_ensure_idempotent(empty_db, bundled_mode) -> None:
    harbor_seed.ensure_harbor_rubrics(empty_db)
    harbor_seed.ensure_harbor_rubrics(empty_db)

    assert empty_db.execute(
        "SELECT COUNT(*) AS n FROM rubrics WHERE source LIKE 'harbor:%%'"
    ).fetchone()["n"] == 2
    assert empty_db.execute("SELECT COUNT(*) AS n FROM criteria").fetchone()["n"] == 13
    # No duplicate criteria within a rubric (UNIQUE(rubric_id, name)).
    assert empty_db.execute(
        "SELECT COUNT(*) AS n FROM criteria c1, criteria c2 "
        "WHERE c1.rubric_id = c2.rubric_id AND c1.name = c2.name AND c1.id < c2.id"
    ).fetchone()["n"] == 0


def test_ensure_preserves_local_and_eval(empty_db, bundled_mode) -> None:
    # Build a DB that looks like the stale volume: schema + a local rubric and
    # an eval_runs row, but no harbor rubrics.
    store.ensure_schema(empty_db)
    harbor_seed.create_schema(empty_db)
    now = "2026-01-01T00:00:00+00:00"
    empty_db.execute(
        "INSERT INTO rubrics (name, context, source, description, created_at) "
        "VALUES ('my_local', 'contract', 'local', 'a local rubric', %s)",
        (now,),
    )
    local_id = empty_db.execute(
        "SELECT id FROM rubrics WHERE name = 'my_local'"
    ).fetchone()["id"]
    empty_db.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "VALUES (%s, 'c1', 'd', 'g', 0)",
        (local_id,),
    )
    empty_db.execute(
        "INSERT INTO eval_runs (rubric_name, contract_path, score, max_score, "
        "all_pass, n_criteria, n_passed, scored_at, created_at) "
        "VALUES ('my_local', 'c.md', 0.5, 1.0, 0, 1, 0, %s, %s)",
        (now, now),
    )
    empty_db.commit()

    harbor_seed.ensure_harbor_rubrics(empty_db)

    # Local rubric + its criterion are untouched.
    local = empty_db.execute(
        "SELECT description FROM rubrics WHERE name = 'my_local' AND source = 'local'"
    ).fetchone()
    assert local is not None and local["description"] == "a local rubric"
    assert empty_db.execute(
        "SELECT COUNT(*) AS n FROM criteria WHERE rubric_id = %s", (local_id,)
    ).fetchone()["n"] == 1
    # The eval_runs row is untouched.
    run = empty_db.execute("SELECT rubric_name, score FROM eval_runs").fetchone()
    assert run["rubric_name"] == "my_local" and run["score"] == 0.5
    # Harbor rubrics were added alongside.
    assert empty_db.execute(
        "SELECT COUNT(*) AS n FROM rubrics WHERE source LIKE 'harbor:%%'"
    ).fetchone()["n"] == 2


def test_load_uses_bundled_when_harbor_absent(monkeypatch) -> None:
    monkeypatch.setattr(harbor_seed, "find_harbor_package", lambda: None)

    loaded, origin = harbor_seed.load_harbor_rubrics()

    assert origin == "bundled"
    assert len(loaded) == 2
    names = sorted(r["name"] for r, _c, _s in loaded)
    assert names == ["task_quality", "trial_behavior"]
    assert all(s == "harbor:v0.20.0" for _r, _c, s in loaded)
    total_criteria = sum(len(c) for _r, c, _s in loaded)
    assert total_criteria == 13
