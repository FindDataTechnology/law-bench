"""Tests for the quarterly judge-drift meta-eval job (task 6.3).

Covers ``scripts/drift_check.py`` — the deterministic comparator between the
two newest generations of stored judge calibrations (or two calibration-result
JSON files):

- threshold resolution: CLI flag > ``DRIFT_THRESHOLD`` env > default 0.05, and
  loud failure on invalid values;
- the pure comparison arithmetic: agree-rate drop strictly greater than the
  threshold, the monotonic yes->no flip, the exact-threshold boundary, and the
  honest ``not_comparable`` paths;
- DB mode on the throwaway per-test ``empty_db``: a healthy baseline run plus a
  degraded current run is flagged, the ``channel='meta' / unit_kind='drift'``
  record with its three diagnostic criteria rows is stored, and drift records
  never pollute the calibration-run pairing query;
- no-baseline and single-run paths report ``not_comparable`` honestly and store
  nothing;
- file-diff mode over two calibration-result JSONs, including judge/version
  resolution and mismatch errors;
- the ``main`` CLI entry points and exit codes (0 ok / not_comparable,
  1 drift alarm, 2 bad input), with the script's ``connect`` monkeypatched onto
  the fixture connection so the process-wide shared connection is never opened.

All gold records are synthetic in-process pairs; no LLM, no network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import drift_check as dc  # noqa: E402

from src.bench.calibration import run_calibration  # noqa: E402
from src.eval.store import ensure_schema  # noqa: E402

JUDGE = "judge-drift"
VERSION = "v2-structure"

CRIT_IDS = ["compare:agree_rate_drop", "compare:monotonicity", "compare:sample_size"]


# --------------------------------------------------------------------------- #
# synthetic gold record builders (judge/human verdict pairs, fully controlled) #
# --------------------------------------------------------------------------- #


def _rec(conf, judge, human):
    return {"confidence": conf, "judge_verdict": judge, "human_verdict": human}


def _agreeing(conf, n):
    """n records where the judge agrees with the human."""
    return [_rec(conf, True, True) for _ in range(n)]


def _disagreeing(conf, n):
    """n records where the judge disagrees with the human."""
    return [_rec(conf, False, True) for _ in range(n)]


def _baseline_records():
    """Healthy baseline: 60 pairs, agree rate 0.9, monotonic 0.80->0.90->1.00."""
    return (
        _agreeing(0.55, 16) + _disagreeing(0.55, 4)  # [0.5,0.6): 0.80
        + _agreeing(0.75, 18) + _disagreeing(0.75, 2)  # [0.7,0.8): 0.90
        + _agreeing(0.95, 20)  # [0.9,1.0]: 1.00
    )


def _at_threshold_records():
    """60 pairs, agree rate exactly 0.85 (drop == threshold 0.05), still
    monotonic (0.80->0.85->0.90): must NOT be flagged, drift needs a drop
    *strictly greater* than the threshold."""
    return (
        _agreeing(0.55, 16) + _disagreeing(0.55, 4)  # [0.5,0.6): 0.80
        + _agreeing(0.75, 17) + _disagreeing(0.75, 3)  # [0.7,0.8): 0.85
        + _agreeing(0.95, 18) + _disagreeing(0.95, 2)  # [0.9,1.0]: 0.90
    )


def _dropped_records():
    """60 pairs, agree rate 50/60 = 0.8333 (drop 0.0667 > 0.05) while buckets
    stay monotonic (0.80->0.85->0.85): drift fires on the agree-rate only."""
    return (
        _agreeing(0.55, 16) + _disagreeing(0.55, 4)  # [0.5,0.6): 0.80
        + _agreeing(0.75, 17) + _disagreeing(0.75, 3)  # [0.7,0.8): 0.85
        + _agreeing(0.95, 17) + _disagreeing(0.95, 3)  # [0.9,1.0]: 0.85
    )


def _flip_records():
    """40 pairs, agree rate exactly 0.9 (zero agree-rate drop), but bucket
    accuracy 1.00->1.00->0.80 breaks monotonicity: flip-only drift."""
    return (
        _agreeing(0.55, 10)
        + _agreeing(0.75, 10)
        + _agreeing(0.95, 16) + _disagreeing(0.95, 4)  # [0.9,1.0]: 0.80
    )


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    """Per-test throwaway DB with the eval schema ensured on the fixture conn."""
    ensure_schema(db_path=empty_db)
    yield empty_db


def _calibrate(conn, records, judge=JUDGE, version=VERSION):
    return run_calibration(
        conn,
        judge_model=judge,
        prompt_version=version,
        gold_records=records,
        db_path=conn,
    )


def _drift_rows(conn):
    return conn.execute(
        "SELECT id, rubric_name, channel, unit_kind, score, max_score, all_pass, "
        "       n_criteria, n_passed, summary, judge_model, task_desc "
        "FROM eval_runs WHERE unit_kind = 'drift' ORDER BY id"
    ).fetchall()


def _criteria_rows(conn, run_id):
    return conn.execute(
        "SELECT criterion_id, title, verdict, reasoning, ordinal "
        "FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal",
        (run_id,),
    ).fetchall()


def _cal(agree, mono, n=60, run_id=None):
    """A normalized calibration dict of the shape compare_calibrations eats."""
    return {
        "source": "test",
        "run_id": run_id,
        "agree_rate": agree,
        "monotonic": mono,
        "n": n,
    }


# --------------------------------------------------------------------------- #
# threshold resolution: CLI > env DRIFT_THRESHOLD > default, invalid -> raise  #
# --------------------------------------------------------------------------- #


class TestResolveThreshold:
    def test_default_is_005(self, monkeypatch):
        monkeypatch.delenv("DRIFT_THRESHOLD", raising=False)
        assert dc.resolve_threshold() == pytest.approx(0.05)

    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv("DRIFT_THRESHOLD", "0.20")
        assert dc.resolve_threshold() == pytest.approx(0.20)

    def test_cli_value_overrides_env(self, monkeypatch):
        monkeypatch.setenv("DRIFT_THRESHOLD", "0.20")
        assert dc.resolve_threshold(0.01) == pytest.approx(0.01)

    def test_env_outside_unit_interval_raises(self, monkeypatch):
        monkeypatch.setenv("DRIFT_THRESHOLD", "1.5")
        with pytest.raises(ValueError, match="DRIFT_THRESHOLD"):
            dc.resolve_threshold()

    def test_env_not_a_number_raises(self, monkeypatch):
        monkeypatch.setenv("DRIFT_THRESHOLD", "often")
        with pytest.raises(ValueError, match="not a number"):
            dc.resolve_threshold()


# --------------------------------------------------------------------------- #
# pure comparison arithmetic (no DB, no clock, no LLM)                          #
# --------------------------------------------------------------------------- #


class TestCompareCalibrations:
    def test_drop_strictly_above_threshold_is_drift(self):
        report = dc.compare_calibrations(_cal(0.9, True), _cal(0.84, True), 0.05)
        assert report["status"] == "drift"
        assert report["agree_rate_drift"] is True
        assert report["monotonicity_flip"] is False
        assert report["agree_rate_drop"] == pytest.approx(0.06)

    def test_drop_exactly_at_threshold_is_not_drift(self):
        # 0.9 - 0.85 == 0.050000000000000044 in IEEE-754; the epsilon guard
        # must keep the exact-threshold drop on the "ok" side of the
        # "strictly greater" condition.
        report = dc.compare_calibrations(_cal(0.9, True), _cal(0.85, True), 0.05)
        assert report["status"] == "ok"
        assert report["agree_rate_drift"] is False

    def test_improvement_is_never_drift(self):
        report = dc.compare_calibrations(_cal(0.8, True), _cal(0.95, True), 0.05)
        assert report["status"] == "ok"
        assert report["agree_rate_drop"] == pytest.approx(-0.15)

    def test_monotonic_flip_yes_to_no_is_drift_even_without_agree_drop(self):
        report = dc.compare_calibrations(_cal(0.9, True), _cal(0.9, False), 0.05)
        assert report["status"] == "drift"
        assert report["agree_rate_drift"] is False
        assert report["monotonicity_flip"] is True

    def test_no_to_no_is_not_a_flip_and_no_to_yes_is_ok(self):
        assert dc.compare_calibrations(
            _cal(0.9, False), _cal(0.9, False), 0.05
        )["monotonicity_flip"] is False
        report = dc.compare_calibrations(_cal(0.9, False), _cal(0.9, True), 0.05)
        assert report["status"] == "ok"

    def test_threshold_is_respected_numerically(self):
        ok = dc.compare_calibrations(_cal(0.9, True), _cal(0.85, True), 0.10)
        assert ok["status"] == "ok"
        bad = dc.compare_calibrations(_cal(0.9, True), _cal(0.79, True), 0.10)
        assert bad["status"] == "drift"

    def test_missing_fields_are_not_comparable_not_fabricated(self):
        report = dc.compare_calibrations(
            {"agree_rate": None, "monotonic": True}, _cal(0.8, True), 0.05
        )
        assert report["status"] == "not_comparable"
        assert "agree_rate" in report["reason"]
        report = dc.compare_calibrations(_cal(0.9, True), {"agree_rate": 0.8}, 0.05)
        assert report["status"] == "not_comparable"
        assert "monotonic" in report["reason"]


# --------------------------------------------------------------------------- #
# DB mode: compare the two newest stored meta/judge calibration runs            #
# --------------------------------------------------------------------------- #


class TestRunDriftCheckDbMode:
    def test_no_baseline_is_not_comparable_and_stores_nothing(self, db_conn):
        report = dc.run_drift_check(
            db_conn, judge_model=JUDGE, prompt_version=VERSION, db_path=db_conn
        )
        assert report["status"] == "not_comparable"
        assert report["runs_found"] == 0
        assert report["drift_run_id"] is None
        assert "nothing to compare" in report["reason"]
        assert _drift_rows(db_conn) == []

    def test_single_run_is_not_comparable(self, db_conn):
        _calibrate(db_conn, _baseline_records())
        report = dc.run_drift_check(
            db_conn, judge_model=JUDGE, prompt_version=VERSION, db_path=db_conn
        )
        assert report["status"] == "not_comparable"
        assert report["runs_found"] == 1
        assert "need 2 generations" in report["reason"]
        assert _drift_rows(db_conn) == []

    def test_agree_rate_drop_detected_and_recorded(self, db_conn):
        base = _calibrate(db_conn, _baseline_records())  # agree 0.9
        cur = _calibrate(db_conn, _dropped_records())  # agree 0.8333
        report = dc.run_drift_check(
            db_conn, judge_model=JUDGE, prompt_version=VERSION, db_path=db_conn
        )
        assert report["status"] == "drift"
        assert report["agree_rate_drift"] is True
        assert report["monotonicity_flip"] is False
        assert report["agree_rate_drop"] == pytest.approx(0.06667, abs=1e-4)
        assert report["threshold"] == pytest.approx(0.05)
        assert report["baseline"]["run_id"] == base["run_id"]
        assert report["current"]["run_id"] == cur["run_id"]

        rows = _drift_rows(db_conn)
        assert len(rows) == 1
        row = rows[0]
        assert row["rubric_name"] == f"drift-check:{JUDGE}@{VERSION}"
        assert row["channel"] == "meta"
        assert row["unit_kind"] == "drift"
        assert row["judge_model"] == JUDGE
        assert row["task_desc"] == f"prompt_version={VERSION}"
        assert row["score"] == pytest.approx(50 / 60, abs=1e-4)
        assert row["max_score"] == 1.0
        assert row["all_pass"] in (0, False)
        assert (row["n_criteria"], row["n_passed"]) == (3, 2)
        assert "status=drift" in row["summary"]

        crits = _criteria_rows(db_conn, row["id"])
        assert [c["criterion_id"] for c in crits] == CRIT_IDS
        assert [c["ordinal"] for c in crits] == [0, 1, 2]
        verdicts = {c["criterion_id"]: c["verdict"] for c in crits}
        assert verdicts["compare:agree_rate_drop"] == "fail"
        assert verdicts["compare:monotonicity"] == "pass"
        assert verdicts["compare:sample_size"] == "pass"
        drop_row = next(c for c in crits if c["criterion_id"] == "compare:agree_rate_drop")
        assert "drift" in drop_row["reasoning"]
        assert "threshold 0.05" in drop_row["reasoning"]
        sample_row = next(c for c in crits if c["criterion_id"] == "compare:sample_size")
        assert f"baseline n=60 (run {base['run_id']})" in sample_row["reasoning"]
        assert f"current n=60 (run {cur['run_id']})" in sample_row["reasoning"]

    def test_monotonicity_flip_only_detected(self, db_conn):
        _calibrate(db_conn, _baseline_records())  # 0.9 monotonic
        _calibrate(db_conn, _flip_records())  # 0.9 not monotonic
        report = dc.run_drift_check(
            db_conn, judge_model=JUDGE, prompt_version=VERSION, db_path=db_conn
        )
        assert report["status"] == "drift"
        assert report["agree_rate_drift"] is False
        assert report["monotonicity_flip"] is True
        row = _drift_rows(db_conn)[0]
        verdicts = {
            c["criterion_id"]: c["verdict"] for c in _criteria_rows(db_conn, row["id"])
        }
        assert verdicts["compare:agree_rate_drop"] == "pass"
        assert verdicts["compare:monotonicity"] == "fail"

    def test_exact_threshold_drop_is_ok_but_still_recorded(self, db_conn):
        _calibrate(db_conn, _baseline_records())  # 0.9
        _calibrate(db_conn, _at_threshold_records())  # 0.85, drop exactly 0.05
        report = dc.run_drift_check(
            db_conn, judge_model=JUDGE, prompt_version=VERSION, db_path=db_conn
        )
        assert report["status"] == "ok"
        assert report["agree_rate_drift"] is False
        row = _drift_rows(db_conn)[0]
        assert row["all_pass"] in (1, True)
        assert "status=ok" in row["summary"]

    def test_env_threshold_can_suppress_the_alarm(self, db_conn, monkeypatch):
        _calibrate(db_conn, _baseline_records())
        _calibrate(db_conn, _dropped_records())  # drop 0.0667
        monkeypatch.setenv("DRIFT_THRESHOLD", "0.20")
        report = dc.run_drift_check(
            db_conn, judge_model=JUDGE, prompt_version=VERSION, db_path=db_conn
        )
        assert report["status"] == "ok"
        assert report["threshold"] == pytest.approx(0.20)
        # an explicit argument still beats the env
        report = dc.run_drift_check(
            db_conn,
            judge_model=JUDGE,
            prompt_version=VERSION,
            threshold=0.05,
            db_path=db_conn,
        )
        assert report["status"] == "drift"

    def test_drift_records_never_pollute_the_calibration_pairing(self, db_conn):
        _calibrate(db_conn, _baseline_records())
        _calibrate(db_conn, _dropped_records())
        first = dc.run_drift_check(
            db_conn, judge_model=JUDGE, prompt_version=VERSION, db_path=db_conn
        )
        assert first["status"] == "drift"
        # the fetch still sees exactly the two judge runs, newest first
        runs = dc.fetch_calibration_runs(
            db_conn, judge_model=JUDGE, prompt_version=VERSION
        )
        assert len(runs) == 2
        # re-running compares the SAME generation pair again and appends a
        # second audit row, without shifting the pairing
        second = dc.run_drift_check(
            db_conn, judge_model=JUDGE, prompt_version=VERSION, db_path=db_conn
        )
        assert second["status"] == "drift"
        assert second["baseline"]["run_id"] == first["baseline"]["run_id"]
        assert len(_drift_rows(db_conn)) == 2

    def test_blank_identity_raises(self, db_conn):
        with pytest.raises(ValueError, match="judge_model"):
            dc.run_drift_check(
                db_conn, judge_model=" ", prompt_version=VERSION, db_path=db_conn
            )
        with pytest.raises(ValueError, match="prompt_version"):
            dc.run_drift_check(
                db_conn, judge_model=JUDGE, prompt_version="", db_path=db_conn
            )

    def test_versions_are_compared_separately(self, db_conn):
        _calibrate(db_conn, _baseline_records(), version=VERSION)
        _calibrate(db_conn, _dropped_records(), version=VERSION)
        report = dc.run_drift_check(
            db_conn, judge_model=JUDGE, prompt_version="v1-legacy", db_path=db_conn
        )
        assert report["status"] == "not_comparable"
        assert report["runs_found"] == 0


# --------------------------------------------------------------------------- #
# file-diff mode: compare two calibration-result JSONs                          #
# --------------------------------------------------------------------------- #


def _result_json(agree, mono, n, judge=JUDGE, version=VERSION):
    """A file in the shape run_calibration's result dict has."""
    return {
        "rubric": f"judge-calibration:{judge}@{version}",
        "judge_model": judge,
        "prompt_version": version,
        "n": n,
        "agree_rate": agree,
        "monotonic": mono,
        "all_pass": bool(mono) and agree >= 0.8,
    }


class TestFileDiffMode:
    def test_dropped_current_is_drift_and_stored(self, db_conn, tmp_path):
        b = tmp_path / "base.json"
        c = tmp_path / "cur.json"
        b.write_text(json.dumps(_result_json(0.9, True, 60)))
        c.write_text(json.dumps(_result_json(0.8, True, 60)))
        report = dc.run_drift_check_files(
            db_conn,
            baseline_path=b,
            current_path=c,
            judge_model=JUDGE,
            prompt_version=VERSION,
            db_path=db_conn,
        )
        assert report["status"] == "drift"
        row = _drift_rows(db_conn)[0]
        assert row["rubric_name"] == f"drift-check:{JUDGE}@{VERSION}"
        crits = {
            x["criterion_id"]: x["verdict"]
            for x in _criteria_rows(db_conn, row["id"])
        }
        assert crits["compare:agree_rate_drop"] == "fail"

    def test_identity_resolved_from_json_when_flags_omitted(self, db_conn, tmp_path):
        b = tmp_path / "base.json"
        c = tmp_path / "cur.json"
        b.write_text(json.dumps(_result_json(0.9, True, 60)))
        c.write_text(json.dumps(_result_json(0.88, True, 60)))
        report = dc.run_drift_check_files(
            db_conn, baseline_path=b, current_path=c, db_path=db_conn
        )
        assert report["status"] == "ok"
        assert report["judge_model"] == JUDGE
        assert report["prompt_version"] == VERSION
        assert (
            _drift_rows(db_conn)[0]["rubric_name"] == f"drift-check:{JUDGE}@{VERSION}"
        )

    def test_mismatched_judge_between_files_is_a_caller_error(self, db_conn, tmp_path):
        b = tmp_path / "base.json"
        c = tmp_path / "cur.json"
        b.write_text(json.dumps(_result_json(0.9, True, 60)))
        c.write_text(json.dumps(_result_json(0.8, True, 60, judge="judge-other")))
        with pytest.raises(ValueError, match="does not match"):
            dc.run_drift_check_files(
                db_conn, baseline_path=b, current_path=c, db_path=db_conn
            )

    def test_unparseable_json_fields_yield_not_comparable_without_storing(
        self, db_conn, tmp_path
    ):
        b = tmp_path / "base.json"
        c = tmp_path / "cur.json"
        b.write_text(json.dumps({"agree_rate": 0.9, "monotonic": True}))
        c.write_text(json.dumps({"agree_rate": 0.5}))  # no monotonic key
        report = dc.run_drift_check_files(
            db_conn,
            baseline_path=b,
            current_path=c,
            judge_model=JUDGE,
            prompt_version=VERSION,
            db_path=db_conn,
        )
        assert report["status"] == "not_comparable"
        assert report["drift_run_id"] is None
        assert _drift_rows(db_conn) == []


# --------------------------------------------------------------------------- #
# CLI main(): exit codes and JSON stdout                                        #
# --------------------------------------------------------------------------- #


class TestCliMain:
    @pytest.fixture(autouse=True)
    def _inject_conn(self, db_conn, monkeypatch):
        """Route the script's connect() onto the fixture connection, so the CLI
        path stays hermetic and never opens the process-wide shared conn."""
        monkeypatch.setattr(dc, "connect", lambda *a, **k: db_conn)
        self.conn = db_conn

    @staticmethod
    def _stdout_json(capsys):
        return json.loads(capsys.readouterr().out)

    def test_drift_exits_1_and_prints_json_report(self, capsys):
        _calibrate(self.conn, _baseline_records())
        _calibrate(self.conn, _dropped_records())
        rc = dc.main(["--judge-model", JUDGE, "--prompt-version", VERSION])
        assert rc == 1
        report = self._stdout_json(capsys)
        assert report["status"] == "drift"
        assert report["drift_run_id"] is not None
        assert _drift_rows(self.conn)[0]["id"] == report["drift_run_id"]

    def test_ok_exits_0(self, capsys):
        _calibrate(self.conn, _baseline_records())
        _calibrate(self.conn, _at_threshold_records())
        rc = dc.main(["--judge-model", JUDGE, "--prompt-version", VERSION])
        assert rc == 0
        assert self._stdout_json(capsys)["status"] == "ok"

    def test_not_comparable_exits_0_and_stores_nothing(self, capsys):
        rc = dc.main(["--judge-model", "ghost-judge", "--prompt-version", VERSION])
        assert rc == 0
        assert self._stdout_json(capsys)["status"] == "not_comparable"
        assert _drift_rows(self.conn) == []

    def test_missing_identity_flags_is_error_exit_2(self, capsys):
        rc = dc.main([])
        assert rc == 2
        report = self._stdout_json(capsys)
        assert report["status"] == "error"
        assert "--judge-model" in report["reason"]

    def test_explicit_threshold_flag_beats_env(self, capsys, monkeypatch):
        monkeypatch.setenv("DRIFT_THRESHOLD", "0.20")
        _calibrate(self.conn, _baseline_records())
        _calibrate(self.conn, _dropped_records())
        rc = dc.main(
            ["--judge-model", JUDGE, "--prompt-version", VERSION, "--threshold", "0.05"]
        )
        assert rc == 1
        assert self._stdout_json(capsys)["status"] == "drift"

    def test_bad_env_threshold_is_error_exit_2(self, capsys, monkeypatch):
        monkeypatch.setenv("DRIFT_THRESHOLD", "not-a-float")
        rc = dc.main(["--judge-model", JUDGE, "--prompt-version", VERSION])
        assert rc == 2
        assert self._stdout_json(capsys)["status"] == "error"

    def test_file_mode_cli(self, capsys, tmp_path):
        b = tmp_path / "base.json"
        c = tmp_path / "cur.json"
        b.write_text(json.dumps(_result_json(0.9, True, 60)))
        c.write_text(json.dumps(_result_json(0.7, True, 60)))
        rc = dc.main(["--baseline", str(b), "--current", str(c)])
        assert rc == 1
        report = self._stdout_json(capsys)
        assert report["status"] == "drift"
        assert report["judge_model"] == JUDGE
        assert _drift_rows(self.conn)

    def test_file_mode_needs_both_paths(self, capsys, tmp_path):
        b = tmp_path / "base.json"
        b.write_text(json.dumps(_result_json(0.9, True, 60)))
        rc = dc.main(
            [
                "--baseline",
                str(b),
                "--judge-model",
                JUDGE,
                "--prompt-version",
                VERSION,
            ]
        )
        assert rc == 2
        assert "BOTH" in self._stdout_json(capsys)["reason"]


# --------------------------------------------------------------------------- #
# import-safety (the verify_expand.py lesson: no side effects on import)        #
# --------------------------------------------------------------------------- #


class TestImportSideEffectFree:
    def test_main_guard_present_and_no_bare_exit(self):
        text = (SCRIPTS_DIR / "drift_check.py").read_text(encoding="utf-8")
        assert 'if __name__ == "__main__":' in text
        # the module import at the top of this test file already proved the
        # guard works: an unguarded main()/sys.exit() would have exploded here
        assert callable(dc.main)
