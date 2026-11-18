"""Unit tests for the shared helpers in ``src/eval/db.py`` (PostgreSQL)."""

from __future__ import annotations

from src.eval.db import connect, is_harbor, renumber_criteria


def test_connect_returns_dict_row_connection(seeded_db):
    # connect() on a live connection returns a borrowed wrapper whose rows are
    # dicts (psycopg dict_row); close() is a no-op so the fixture owns the conn.
    conn = connect(seeded_db)
    row = conn.execute("SELECT id, name FROM rubrics WHERE name = 'l_rubric'").fetchone()
    assert row is not None
    assert row["name"] == "l_rubric"  # dict-row access, not tuple
    conn.close()  # no-op (borrowed)


def test_is_harbor_predicate():
    assert is_harbor("harbor:v0.20.0") is True
    assert is_harbor("local") is False
    assert is_harbor(None) is False
    assert is_harbor("") is False


def test_renumber_criteria_contiguous(seeded_db):
    rid = seeded_db.execute(
        "SELECT id FROM rubrics WHERE name = 'l_rubric'"
    ).fetchone()["id"]
    # punch gaps in the ordinals, then renumber
    seeded_db.execute(
        "UPDATE criteria SET ordinal = 5 WHERE rubric_id = %s", (rid,)
    )
    seeded_db.commit()
    renumber_criteria(seeded_db, rid)
    ordinals = [
        r["ordinal"]
        for r in seeded_db.execute(
            "SELECT ordinal FROM criteria WHERE rubric_id = %s ORDER BY ordinal",
            (rid,),
        ).fetchall()
    ]
    seeded_db.commit()
    assert ordinals == [0, 1]


def test_fk_cascade_deletes_criteria(seeded_db):
    # PostgreSQL enforces ON DELETE CASCADE (foreign keys are on by default).
    rid = seeded_db.execute(
        "SELECT id FROM rubrics WHERE name = 'l_rubric'"
    ).fetchone()["id"]
    seeded_db.execute("DELETE FROM rubrics WHERE id = %s", (rid,))
    seeded_db.commit()
    n = seeded_db.execute(
        "SELECT COUNT(*) AS n FROM criteria WHERE rubric_id = %s", (rid,)
    ).fetchone()["n"]
    assert n == 0
