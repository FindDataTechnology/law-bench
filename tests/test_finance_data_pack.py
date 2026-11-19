"""Tests for the finance-data domain pack (packs/finance-data/).

Data source discipline: the tests monkeypatch ``FD_SENTIMENT_REPO`` to the
real sibling repo ``<workspace>/fd-sentiment`` (the gold file
``gold/gold-v9.json`` exists there — verified 2026-11-03, 105 items), so every
truth assertion runs against real data. **No gold data is fabricated in this
repo**: the only fixture under ``tests/fixtures/finance/`` is a deliberately
broken gold file (an item missing ``expected_band``) used to prove the loader
raises honestly; if the sibling repo is absent, the real-data tests skip
rather than invent.

Coverage:
- pack.yaml passes ``validate_pack`` (name/directory match, components exist);
- ``load_sentiment_gold`` is idempotent (two runs, same count, no dup rows)
  and maps attrs faithfully to the file's own values;
- the deterministic checkers registered for kind='fact' pass/fail as designed;
- ``run_data_eval`` full chain on ``empty_db`` + ``ensure_schema(db_path=conn)``
  lands channel='data' eval_runs + per-checker criteria rows;
- ``build_data_qa_goldset``: every question's judge is executable and passes
  on the real truth, and every expected value is traceable to the gold file.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
import yaml

from src.bench.data_checks import checkers_for, run_data_eval
from src.bench.packs import load_pack, validate_pack
from src.bench.store import list_knowledge_units, upsert_knowledge_unit
from src.eval.store import ensure_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = REPO_ROOT / "packs" / "finance-data"
SIBLING = REPO_ROOT.parent / "fd-sentiment"
REAL_GOLD = SIBLING / "gold" / "gold-v9.json"
BROKEN_GOLD_DIR = REPO_ROOT / "tests" / "fixtures" / "finance" / "broken-gold"

# The real first item of gold-v9 (verified against the sibling file) — used as
# the good-unit fixture for checker true-cases; values are real, not invented.
FIRST_ITEM = {
    "doc_id": "1200474144",
    "as_of": "2014-12-17",
    "expected_band": "neutral",
    "text_sha256": "940f83cdd3a943b5c52c4cc4b8bf1c6ba08b992d605b959d0cca57d7bcd8ef1d",
    "text_chars": 1114,
}


def _mods():
    """Import the pack's modules (hyphenated dir -> importlib) and return them."""
    adapters = importlib.import_module("packs.finance-data.adapters")
    checks = importlib.import_module("packs.finance-data.checks")
    return adapters, checks


@pytest.fixture()
def fact_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    """Per-test DB with the platform schema + finance-data checkers registered."""
    ensure_schema(db_path=empty_db)
    _mods()  # import-time registration
    yield empty_db


@pytest.fixture()
def real_sentiment_repo(monkeypatch):
    """Point FD_SENTIMENT_REPO at the real sibling repo (skip if absent)."""
    if not REAL_GOLD.is_file():
        pytest.skip(
            f"fd-sentiment sibling repo not found at {SIBLING}; "
            "the finance-data pack intentionally does not copy gold data"
        )
    monkeypatch.setenv("FD_SENTIMENT_REPO", str(SIBLING))
    return SIBLING


def _real_items() -> list[dict]:
    return json.loads(REAL_GOLD.read_text(encoding="utf-8"))["items"]


# ---------------------------------------------------------------- pack.yaml --


class TestPackManifest:
    def test_pack_yaml_validates_clean(self):
        manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
        assert manifest["name"] == "finance-data"
        assert "fact" in manifest["kinds"]
        assert {"sentiment-gold-v9", "data-qa-goldset"} <= set(manifest["eval_suites"])
        # Components are real repo-internal paths (no sibling-repo references).
        assert manifest["components"], "pack must declare its components"
        for comp in manifest["components"]:
            assert comp["type"] in ("module", "data", "db_seed")
            path = REPO_ROOT / comp["path"]
            assert path.is_file(), f"component path must exist: {comp['path']}"
            assert str(SIBLING) not in comp["path"]
        assert validate_pack(manifest, directory="finance-data") == []

    def test_pack_discoverable_via_registry(self):
        manifest = load_pack("finance-data")
        assert validate_pack(manifest, directory="finance-data") == []


# ------------------------------------------------------------------ adapter --


class TestLoadSentimentGold:
    def test_load_is_idempotent_and_maps_real_attrs(
        self, fact_conn, real_sentiment_repo
    ):
        adapters, _ = _mods()
        expected = len(_real_items())  # truth straight from the sibling file

        n1 = adapters.load_sentiment_gold(fact_conn)
        n2 = adapters.load_sentiment_gold(fact_conn)

        assert n1 == n2 == expected
        rows = list_knowledge_units(
            fact_conn, kind="fact", namespace="finance-data", limit=1000
        )
        assert len(rows) == expected, "re-run must upsert, not duplicate"
        assert all(r["tier"] == "gold" for r in rows)
        assert all(r["external_key"] == r["attrs"]["doc_id"] for r in rows)

        # Attrs round-trip faithfully against the file's own first item.
        by_key = {r["external_key"]: r for r in rows}
        item = _real_items()[0]
        unit = by_key[item["doc_id"]]
        assert unit["attrs"]["expected_band"] == item["expected_band"]
        assert unit["attrs"]["as_of"] == item["as_of"]
        assert unit["attrs"]["text_sha256"] == item["text_sha256"]
        assert unit["attrs"]["text_chars"] == item["text_chars"]
        assert unit["attrs"]["gold_set"] == "gold-v9"
        assert unit["attrs"]["direction"] == adapters.BAND_TO_DIRECTION[
            item["expected_band"]
        ]
        assert unit["provenance"]["file"] == "gold/gold-v9.json"
        assert str(SIBLING) in unit["source_path"]

    def test_load_raises_when_repo_missing(self, fact_conn, monkeypatch, tmp_path):
        adapters, _ = _mods()
        monkeypatch.setenv("FD_SENTIMENT_REPO", str(tmp_path))  # no gold file here
        with pytest.raises(FileNotFoundError):
            adapters.load_sentiment_gold(fact_conn)

    def test_load_raises_on_malformed_item(self, fact_conn, monkeypatch):
        adapters, _ = _mods()
        monkeypatch.setenv("FD_SENTIMENT_REPO", str(BROKEN_GOLD_DIR))
        with pytest.raises(ValueError, match="expected_band"):
            adapters.load_sentiment_gold(fact_conn)
        assert (
            list_knowledge_units(fact_conn, kind="fact", limit=10) == []
        ), "a failed load must not leave partial rows"

    def test_sentiment_repo_env_override(self, monkeypatch):
        adapters, _ = _mods()
        monkeypatch.setenv("FD_SENTIMENT_REPO", "/tmp/nowhere")
        assert adapters.sentiment_repo() == Path("/tmp/nowhere")
        monkeypatch.delenv("FD_SENTIMENT_REPO")
        assert adapters.sentiment_repo() == adapters.SENTIMENT_REPO
        assert adapters.SENTIMENT_REPO.name == "fd-sentiment"


# ------------------------------------------------------------------ checkers --

# (checker name, good unit, bad unit) — real first-item values for good cases.
GOOD_UNIT = {
    "kind": "fact",
    "namespace": "finance-data",
    "external_key": FIRST_ITEM["doc_id"],
    "body": "gold sample",
    "attrs": {
        **FIRST_ITEM,
        "direction": "neutral",
        "gold_set": "gold-v9",
    },
}


def _unit_with(**attr_overrides):
    unit = json.loads(json.dumps(GOOD_UNIT))  # deep copy
    unit["attrs"].update(attr_overrides)
    return unit


CHECKER_CASES = {
    "band-vocabulary": (_unit_with(), _unit_with(expected_band="涨停")),
    "band-direction-consistency": (
        _unit_with(),
        _unit_with(expected_band="neutral", direction="bullish"),
    ),
    "text-fingerprint-sha256": (_unit_with(), _unit_with(text_sha256="deadbeef")),
    "text-chars-positive": (_unit_with(), _unit_with(text_chars=0)),
    "doc-id-identity": (_unit_with(), _unit_with(doc_id="999")),
    "as-of-iso-date": (_unit_with(), _unit_with(as_of="2014/12/17")),
    "amount-anchor-parseable": (_unit_with(), _unit_with(amount_yi="很多钱")),
}


class TestFactCheckers:
    def test_at_least_three_checkers_registered_at_import(self):
        names = list(checkers_for("fact"))
        assert len(names) >= 3
        assert "band-vocabulary" in names
        assert "band-direction-consistency" in names

    @pytest.mark.parametrize("name", sorted(CHECKER_CASES))
    def test_checker_true_and_false_case(self, name):
        _, checks = _mods()
        fn = checkers_for("fact")[name]
        good, bad = CHECKER_CASES[name]
        assert fn(good).passed is True, f"{name} must pass on a well-formed unit"
        result = fn(bad)
        assert result.passed is False, f"{name} must fail on {bad['attrs']}"
        assert result.detail, "checker must explain its verdict"

    def test_registration_scoped_to_the_fact_kind(self):
        names = list(checkers_for("fact"))
        assert "band-vocabulary" in names
        assert "no-such-kind" not in names
        assert checkers_for("clause") == {}  # other kinds untouched

    def test_amount_anchor_accepts_none_and_numbers(self):
        _, checks = _mods()
        fn = checkers_for("fact")["amount-anchor-parseable"]
        # gold-v9 units carry no amount field: None passes (contract is
        # "parseable if present").
        assert fn(_unit_with()).passed is True
        assert fn(_unit_with(amount_yi=5.0)).passed is True
        assert fn(_unit_with(amount_yi=True)).passed is False


# --------------------------------------------------------------- run_data_eval


class TestRunDataEvalFullChain:
    def test_channel_data_run_and_criteria_rows(self, fact_conn, real_sentiment_repo):
        adapters, _ = _mods()
        n_units = adapters.load_sentiment_gold(fact_conn)
        n_checkers = len(checkers_for("fact"))

        run_id = run_data_eval(fact_conn, kind="fact", db_path=fact_conn)

        row = fact_conn.execute(
            "SELECT rubric_name, judge_model, channel, unit_kind, score, max_score,"
            "       all_pass, n_criteria, n_passed, summary"
            " FROM eval_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert row["channel"] == "data"
        assert row["unit_kind"] == "fact"
        assert row["rubric_name"] == "data-checks:fact"
        assert row["judge_model"] == "deterministic"
        assert (row["n_criteria"], row["max_score"]) == (n_units * n_checkers,) * 2
        # The real gold-v9 data satisfies every deterministic contract above
        # (verified against the sibling file), so the run is an honest all-pass.
        assert row["all_pass"] in (1, True)
        assert row["n_passed"] == row["n_criteria"]
        assert row["summary"] == f"deterministic data checks: {row['n_passed']}/{row['n_criteria']} passed"

        crits = fact_conn.execute(
            "SELECT title, verdict FROM eval_criteria_results WHERE run_id = %s",
            (run_id,),
        ).fetchall()
        assert len(crits) == row["n_criteria"]
        assert {c["title"] for c in crits} == set(checkers_for("fact"))
        assert all(c["verdict"] == "PASS" for c in crits)

    def test_run_data_eval_unknown_unit_raises(self, fact_conn, real_sentiment_repo):
        adapters, _ = _mods()
        adapters.load_sentiment_gold(fact_conn)
        with pytest.raises(KeyError):
            run_data_eval(fact_conn, kind="fact", unit_ids=["nope"], db_path=fact_conn)


# -------------------------------------------------------------- data-QA goldset


class TestDataQaGoldset:
    def test_questions_are_executable_and_truth_passes(
        self, fact_conn, real_sentiment_repo
    ):
        adapters, checks = _mods()
        records = adapters.read_gold_records()
        questions = checks.build_data_qa_goldset(records)

        assert len(questions) >= 5
        # Deterministic: rebuilding from the same records yields the same set.
        assert checks.build_data_qa_goldset(records) == questions

        # Load the real data and index the stored units by external_key.
        adapters.load_sentiment_gold(fact_conn)
        units_by_key = {
            r["external_key"]: r
            for r in list_knowledge_units(
                fact_conn, kind="fact", namespace="finance-data", limit=1000
            )
        }

        # Every expected value must be traceable to the real gold file, and
        # every named judge must execute and pass on the real truth.
        items_by_id = {i["doc_id"]: i for i in _real_items()}
        for q in questions:
            assert q["judge"] in checks.JUDGE_FUNCS, q["qid"]
            item = items_by_id[q["unit_key"]]
            if q["field"] == "expected_band":
                assert q["expected"] == item["expected_band"]
            elif q["field"] == "direction":
                assert q["expected"] == adapters.BAND_TO_DIRECTION[
                    item["expected_band"]
                ]
            elif q["field"] == "text_sha256":
                assert q["expected"] == item["text_sha256"]
            elif q["field"] == "text_chars":
                assert q["expected"] == item["text_chars"]
            else:  # pragma: no cover - guards future fields
                pytest.fail(f"unexpected goldset field {q['field']!r}")

            verdicts = checks.evaluate_goldset([q], units_by_key)
            assert verdicts[0]["passed"] is True, (
                f"{q['qid']} must pass on the real gold truth"
            )

    def test_band_and_direction_coverage_matches_file(self, real_sentiment_repo):
        adapters, checks = _mods()
        records = adapters.read_gold_records()
        questions = checks.build_data_qa_goldset(records)
        bands = {r["expected_band"] for r in records}
        directions = {adapters.BAND_TO_DIRECTION[b] for b in bands}
        band_qs = {q["qid"] for q in questions if q["field"] == "expected_band"}
        dir_qs = {q["qid"] for q in questions if q["field"] == "direction"}
        assert len(band_qs) == len(bands)
        assert len(dir_qs) == len(directions)
        assert len(questions) == len(bands) + len(directions) + 2

    def test_empty_records_rejected(self, real_sentiment_repo):
        _, checks = _mods()
        with pytest.raises(ValueError, match="non-empty"):
            checks.build_data_qa_goldset([])

    def test_unknown_judge_fails_loudly(self, real_sentiment_repo):
        adapters, checks = _mods()
        records = adapters.read_gold_records()
        question = checks.build_data_qa_goldset(records)[0]
        bad = {**question, "judge": "no-such-judge"}
        unit = {"attrs": dict(records[0])}
        with pytest.raises(KeyError, match="no-such-judge"):
            checks.evaluate_goldset([bad], {question["unit_key"]: unit})


# --------------------------------------------------- guard: no sibling writes --

def test_pack_declares_no_data_files_from_sibling_repos():
    """The pack must not reference sibling-repo paths as components (read-only)."""
    manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
    for comp in manifest["components"]:
        assert "fd-sentiment" not in comp["path"]
        assert "fd-data-quality" not in comp["path"]
        assert "dashboards" not in comp["path"]


def test_upsert_roundtrip_via_record_to_unit(empty_db):
    """record_to_unit output upserts cleanly without the loader (kernel fit)."""
    ensure_schema(db_path=empty_db)
    adapters, _ = _mods()
    record = {
        **FIRST_ITEM,
        "set_version": "gold-v9",
        "built_at": "2026-10-21",
        "source_file": str(REAL_GOLD),
    }
    stored = upsert_knowledge_unit(empty_db, **adapters.record_to_unit(record))
    assert stored["kind"] == "fact"
    assert stored["namespace"] == "finance-data"
    assert stored["tier"] == "gold"
    assert stored["body"], "body must be a non-empty description"
