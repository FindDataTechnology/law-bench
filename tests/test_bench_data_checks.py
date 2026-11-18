"""Tests for the deterministic (data) evaluation channel (src/bench/data_checks.py).

Fake checkers are registered against a synthetic unit kind and run over
``knowledge_units`` through :func:`run_data_eval`. The assertions pin the
honest bookkeeping:

- the aggregated run reads ``channel='data'``, ``unit_kind=<kind>``,
  ``rubric_name='data-checks:<kind>'``, ``judge_model='deterministic'``;
- one criteria row per (unit, checker) with verdict ``PASS``/``FAIL`` and
  ``reasoning`` equal to the checker's detail — including the plain-bool
  checker coercion path;
- ``unit_ids`` selects exactly the requested units; unknown keys raise;
- an empty selection records an honest empty run (never a vacuous all-pass);
- nothing ever calls a judge/LLM (checkers are plain functions; the run's
  judge_model is the ``'deterministic'`` sentinel).

Uses the ``empty_db`` fixture with ``ensure_schema(db_path=<connection>)``
injection, so every test runs on its own throwaway database and never touches
the process-wide shared connection.
"""

from __future__ import annotations

import pytest

import src.bench.data_checks as dc
from src.bench.data_checks import (
    CheckResult,
    checkers_for,
    register_checker,
    run_data_eval,
)
from src.bench.store import upsert_knowledge_unit
from src.eval.store import ensure_schema

KIND = "qa-pair"


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so the DDL lands on the per-test DB
    # instead of the process-wide cached shared connection.
    ensure_schema(db_path=empty_db)
    yield empty_db


@pytest.fixture()
def registry():
    """Snapshot/restore the module-level checker registry around each test."""
    saved = {k: dict(v) for k, v in dc._CHECKERS.items()}
    yield dc
    dc._CHECKERS.clear()
    dc._CHECKERS.update(saved)


def _seed_units(conn, n=2, namespace="testns"):
    """Upsert n units of KIND; returns their external keys in seed order."""
    keys = []
    for i in range(1, n + 1):
        key = f"q-{i:03d}"
        upsert_knowledge_unit(
            conn,
            kind=KIND,
            external_key=key,
            body=f"unit body {i}",
            namespace=namespace,
            tier="silver",
            attrs={"i": i},
        )
        keys.append(key)
    return keys


def _fetch_run(conn, run_id):
    return conn.execute(
        "SELECT rubric_name, judge_model, channel, unit_kind, score, max_score, "
        "       all_pass, n_criteria, n_passed, summary "
        "FROM eval_runs WHERE id = %s",
        (run_id,),
    ).fetchone()


def _fetch_criteria(conn, run_id):
    return conn.execute(
        "SELECT criterion_id, title, verdict, reasoning, ordinal "
        "FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal",
        (run_id,),
    ).fetchall()


class TestRegistryApi:
    def test_register_and_checkers_for(self, registry):
        fn = lambda unit: True  # noqa: E731
        register_checker("widget", "c1", fn)
        register_checker("widget", "c2", fn)
        assert checkers_for("widget") == {"c1": fn, "c2": fn}
        assert checkers_for("never-registered") == {}

    def test_checkers_for_returns_a_copy(self, registry):
        fn = lambda unit: True  # noqa: E731
        register_checker("widget", "c1", fn)
        snapshot = checkers_for("widget")
        snapshot.pop("c1")
        assert "c1" in checkers_for("widget")

    def test_reregistering_same_name_replaces(self, registry):
        register_checker(KIND, "c", lambda unit: False)
        register_checker(KIND, "c", lambda unit: True)
        assert len(checkers_for(KIND)) == 1
        assert checkers_for(KIND)["c"]({"any": "unit"}) is True


class TestRunDataEval:
    def test_honest_run_and_criteria_rows(self, db_conn, registry):
        _seed_units(db_conn, 2)

        def always_pass(unit):
            return CheckResult(name="always_pass", passed=True, detail="unit looks fine")

        def length_gate(unit):
            ok = len(unit["body"]) >= 10
            return CheckResult(
                name="length_gate", passed=ok, detail=f"len={len(unit['body'])}"
            )

        def parity_bool(unit):
            # Plain-bool return: coerced to a CheckResult with a generic detail.
            return unit["attrs"]["i"] % 2 == 1

        register_checker(KIND, "always_pass", always_pass)
        register_checker(KIND, "length_gate", length_gate)
        register_checker(KIND, "parity_bool", parity_bool)

        run_id = run_data_eval(db_conn, kind=KIND, db_path=db_conn)

        row = _fetch_run(db_conn, run_id)
        assert row["channel"] == "data"
        assert row["unit_kind"] == KIND
        assert row["rubric_name"] == f"data-checks:{KIND}"
        assert row["judge_model"] == "deterministic"
        assert row["summary"] == "deterministic data checks: 5/6 passed"
        # 2 units x 3 checkers; unit i=2 fails only the parity check.
        assert (row["n_criteria"], row["n_passed"], row["max_score"]) == (6, 5, 6)
        assert row["all_pass"] in (0, False)
        assert row["score"] == 5

        crits = _fetch_criteria(db_conn, run_id)
        assert [c["ordinal"] for c in crits] == list(range(6))
        # The store lists most-recently-updated first, so q-002 precedes q-001;
        # within a unit, checkers run in registration order.
        assert [c["criterion_id"] for c in crits] == [
            "testns/q-002::always_pass",
            "testns/q-002::length_gate",
            "testns/q-002::parity_bool",
            "testns/q-001::always_pass",
            "testns/q-001::length_gate",
            "testns/q-001::parity_bool",
        ]
        assert [(c["title"], c["verdict"], c["reasoning"]) for c in crits] == [
            ("always_pass", "PASS", "unit looks fine"),
            ("length_gate", "PASS", "len=11"),
            ("parity_bool", "FAIL", "failed"),
            ("always_pass", "PASS", "unit looks fine"),
            ("length_gate", "PASS", "len=11"),
            ("parity_bool", "PASS", "ok"),
        ]

    def test_all_pass_when_every_check_passes(self, db_conn, registry):
        _seed_units(db_conn, 1)
        register_checker(
            KIND,
            "ok",
            lambda unit: CheckResult(name="ok", passed=True, detail="fine"),
        )
        run_id = run_data_eval(db_conn, kind=KIND, db_path=db_conn)
        row = _fetch_run(db_conn, run_id)
        assert row["all_pass"] in (1, True)
        assert row["n_passed"] == row["n_criteria"] == 1

    def test_unit_ids_selects_exactly_the_requested_units(self, db_conn, registry):
        keys = _seed_units(db_conn, 3)
        register_checker(
            KIND,
            "ok",
            lambda unit: CheckResult(name="ok", passed=True, detail="fine"),
        )
        run_id = run_data_eval(
            db_conn, kind=KIND, unit_ids=[keys[0], keys[2]], db_path=db_conn
        )
        row = _fetch_run(db_conn, run_id)
        assert (row["n_criteria"], row["n_passed"]) == (2, 2)
        crit_ids = {c["criterion_id"] for c in _fetch_criteria(db_conn, run_id)}
        assert crit_ids == {
            f"testns/{keys[0]}::ok",
            f"testns/{keys[2]}::ok",
        }

    def test_unit_ids_preserves_caller_order(self, db_conn, registry):
        keys = _seed_units(db_conn, 3)
        register_checker(KIND, "ok", lambda unit: True)
        run_id = run_data_eval(
            db_conn, kind=KIND, unit_ids=[keys[2], keys[0]], db_path=db_conn
        )
        crit_ids = [c["criterion_id"] for c in _fetch_criteria(db_conn, run_id)]
        assert crit_ids == [f"testns/{keys[2]}::ok", f"testns/{keys[0]}::ok"]

    def test_unit_ids_unknown_key_raises_key_error(self, db_conn, registry):
        _seed_units(db_conn, 1)
        register_checker(KIND, "ok", lambda unit: True)
        with pytest.raises(KeyError, match="nope"):
            run_data_eval(db_conn, kind=KIND, unit_ids=["nope"], db_path=db_conn)
        # Nothing was recorded for the failed run.
        assert db_conn.execute("SELECT count(*) AS n FROM eval_runs").fetchone()["n"] == 0

    def test_no_checkers_registered_raises(self, db_conn, registry):
        _seed_units(db_conn, 1)
        with pytest.raises(ValueError, match="no checkers registered"):
            run_data_eval(db_conn, kind=KIND, db_path=db_conn)

    def test_empty_selection_records_an_honest_empty_run(self, db_conn, registry):
        # A kind with no units: 0 checks, no criteria rows, and all_pass is
        # False — an empty run never claims a vacuous all-pass.
        register_checker(KIND, "ok", lambda unit: True)
        run_id = run_data_eval(db_conn, kind=KIND, db_path=db_conn)
        row = _fetch_run(db_conn, run_id)
        assert (row["n_criteria"], row["n_passed"]) == (0, 0)
        assert row["all_pass"] in (0, False)
        assert _fetch_criteria(db_conn, run_id) == []

    def test_checker_exception_fails_loudly_and_records_nothing(self, db_conn, registry):
        _seed_units(db_conn, 1)

        def broken(unit):
            raise RuntimeError("checker exploded")

        register_checker(KIND, "broken", broken)
        with pytest.raises(RuntimeError, match="checker exploded"):
            run_data_eval(db_conn, kind=KIND, db_path=db_conn)
        assert db_conn.execute("SELECT count(*) AS n FROM eval_runs").fetchone()["n"] == 0

    def test_checker_receives_the_full_unit_dict(self, db_conn, registry):
        _seed_units(db_conn, 1)
        seen = []
        register_checker(KIND, "spy", lambda unit: seen.append(unit) or True)
        run_data_eval(db_conn, kind=KIND, db_path=db_conn)
        assert len(seen) == 1
        unit = seen[0]
        assert unit["kind"] == KIND
        assert unit["external_key"] == "q-001"
        assert unit["namespace"] == "testns"
        assert unit["tier"] == "silver"
        assert unit["attrs"] == {"i": 1}
