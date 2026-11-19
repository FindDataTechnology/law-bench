"""Tests for the gov domain pack (packs/gov/).

Data source discipline: the tests monkeypatch ``FD_GOV_REPO`` to the real
sibling repo ``<workspace>/fd-cn-gov`` (its registry file
``fd_cn_gov/registry/registry.json`` exists there — verified 2026-11-03:
sources 11 / datasource_columns 57 / scraw_configs 11 / organizations 11), so
every truth assertion runs against real data. **No registry data is copied
into this repo**: the only fixture under ``tests/fixtures/gov/`` is a
deliberately broken synthetic registry (a column row dangling at an unknown
source id) used to prove the loader raises honestly; if the sibling repo is
absent, the real-data tests skip rather than invent.

Coverage:
- pack.yaml passes ``validate_pack`` (name/directory match, components exist);
- ``load_gov_registry`` is idempotent (two runs, same count, no dup rows) and
  maps attrs faithfully to the file's own values;
- the deterministic checkers registered for kind='gov-fact' (>=4) pass/fail as
  designed, each with a real true case and a synthetic false case;
- ``run_data_eval`` full chain on ``empty_db`` + ``ensure_schema(db_path=conn)``
  lands channel='data' eval_runs + per-checker criteria rows (all PASS on the
  real registry);
- KG 判据迁移为 v1 降级实现（registry 元数据图对账），zhengxin 未接入 ——
  见 packs/gov/README.md，此处不设相应 kind。
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
PACK_DIR = REPO_ROOT / "packs" / "gov"
SIBLING = REPO_ROOT.parent / "fd-cn-gov"
REAL_REGISTRY = SIBLING / "fd_cn_gov" / "registry" / "registry.json"
BROKEN_REPO_DIR = REPO_ROOT / "tests" / "fixtures" / "gov" / "broken-repo"

KIND = "gov-fact"
NAMESPACE = "gov"
CHECKER_NAMES = (
    "identity-format",
    "url-https-format",
    "category-vocabulary",
    "organization-binding",
    "column-coverage",
    "primary-key-exists",
    "date-anchor-present",
    "scraw-pairing",
)


def _mods():
    """Import the pack's modules and return them (checks import = registration)."""
    adapters = importlib.import_module("packs.gov.adapters")
    checks = importlib.import_module("packs.gov.checks")
    return adapters, checks


@pytest.fixture()
def gov_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    """Per-test DB with the platform schema + gov checkers registered."""
    ensure_schema(db_path=empty_db)
    _mods()  # import-time registration
    yield empty_db


@pytest.fixture()
def real_gov_repo(monkeypatch):
    """Point FD_GOV_REPO at the real sibling repo (skip if absent)."""
    if not REAL_REGISTRY.is_file():
        pytest.skip(
            f"fd-cn-gov sibling repo/registry not found at {REAL_REGISTRY}; "
            "the gov pack intentionally does not copy registry data"
        )
    monkeypatch.setenv("FD_GOV_REPO", str(SIBLING))
    return SIBLING


def _real_sources() -> list[dict]:
    payload = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
    return payload["sources"]


def _good_unit() -> dict:
    """One real registry unit (first source), built through the adapter itself."""
    adapters, _ = _mods()
    rec = adapters.read_registry_records()[0]
    unit = adapters.record_to_unit(rec)
    return {
        "kind": unit["kind"],
        "namespace": unit["namespace"],
        "external_key": unit["external_key"],
        "body": unit["body"],
        "attrs": unit["attrs"],
    }


def _unit_with(**attr_overrides):
    unit = json.loads(json.dumps(_good_unit()))  # deep copy
    unit["attrs"].update(attr_overrides)
    return unit


# ---------------------------------------------------------------- pack.yaml --


class TestPackManifest:
    def test_pack_yaml_validates_clean(self):
        manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
        assert manifest["name"] == "gov"
        assert manifest["version"] == "0.1.0"
        assert KIND in manifest["kinds"]
        assert "gov-registry-consistency" in manifest["eval_suites"]
        # Components are real repo-internal paths (no sibling-repo references).
        assert manifest["components"], "pack must declare its components"
        for comp in manifest["components"]:
            assert comp["type"] in ("module", "data", "db_seed")
            path = REPO_ROOT / comp["path"]
            assert path.is_file(), f"component path must exist: {comp['path']}"
            assert "fd-cn-gov" not in comp["path"]
        assert validate_pack(manifest, directory="gov") == []

    def test_pack_discoverable_via_registry(self):
        manifest = load_pack("gov")
        assert validate_pack(manifest, directory="gov") == []

    def test_pack_declares_no_gold_judge(self):
        """gov is a pure deterministic pack: no judge/calibration claim."""
        manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
        assert "gold_judge" not in manifest

    def test_pack_kinds_are_honest(self):
        """v1 onboarded kinds only: no fabricated zhengxin/graph kinds."""
        manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
        assert manifest["kinds"] == [KIND]


# ------------------------------------------------------------------ adapter --


class TestLoadGovRegistry:
    def test_load_is_idempotent_and_maps_real_attrs(self, gov_conn, real_gov_repo):
        adapters, _ = _mods()
        expected = len(_real_sources())  # truth straight from the sibling file

        n1 = adapters.load_gov_registry(gov_conn)
        n2 = adapters.load_gov_registry(gov_conn)

        assert n1 == n2 == expected
        assert expected > 0
        rows = list_knowledge_units(gov_conn, kind=KIND, namespace=NAMESPACE, limit=1000)
        assert len(rows) == expected, "re-run must upsert, not duplicate"
        assert all(r["tier"] == "silver" for r in rows)
        assert all(r["external_key"] == r["attrs"]["source_name"] for r in rows)

        # Attrs round-trip faithfully against the real file's first source.
        by_key = {r["external_key"]: r for r in rows}
        src = _real_sources()[0]
        unit = by_key[src["name"]]
        attrs = unit["attrs"]
        assert attrs["source_id"] == src["id"]
        assert attrs["label"] == src["label"]
        assert attrs["url"] == src["url"]
        assert attrs["category"] == src["category"]
        assert attrs["category_label"] == src["category_label"]
        assert attrs["config_type"] == src["config"]["type"]
        assert attrs["seed_url"] == src["config"]["seed_url"]
        assert attrs["n_archives"] == len(src["config"]["archives"])
        # Column join comes from the datasource_columns section of the same file.
        payload = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
        file_cols = [
            c for c in payload["datasource_columns"] if c["datasource_id"] == src["id"]
        ]
        assert attrs["n_columns"] == len(file_cols)
        assert {c["column_name"] for c in attrs["columns"]} == {
            c["column_name"] for c in file_cols
        }
        assert attrs["n_primary_keys"] == sum(
            1 for c in file_cols if c["is_primary_key"] == 1
        )
        assert attrs["has_date_column"] is True
        # Organization binding: the <code.lower()>_ name-prefix convention.
        org = next(
            o
            for o in payload["organizations"]
            if src["name"].startswith(o["code"].lower() + "_")
        )
        assert attrs["org_code"] == org["code"]
        assert attrs["org_name_zh"] == org["name_zh"]
        # Scraw pairing: name+url reconcile with the source.
        scraw = next(s for s in payload["scraw_configs"] if s["name"] == src["name"])
        assert attrs["scraw_name"] == scraw["name"]
        assert attrs["scraw_url"] == scraw["url"]

        assert unit["provenance"]["file"] == "fd_cn_gov/registry/registry.json"
        assert unit["provenance"]["source_repo"].startswith("fd-cn-gov")
        assert unit["provenance"]["registry_sha256"], "load must pin the file digest"
        assert str(SIBLING) in unit["source_path"]
        assert unit["body"], "body (label/描述文本) must be non-empty"

    def test_load_raises_when_repo_missing(self, gov_conn, monkeypatch, tmp_path):
        adapters, _ = _mods()
        monkeypatch.setenv("FD_GOV_REPO", str(tmp_path))  # no registry file here
        with pytest.raises(FileNotFoundError):
            adapters.load_gov_registry(gov_conn)

    def test_load_raises_on_dangling_column(self, gov_conn, monkeypatch):
        """A datasource_columns row pointing at an unknown source id is file
        corruption: the loader rejects the whole file, never drops rows."""
        adapters, _ = _mods()
        monkeypatch.setenv("FD_GOV_REPO", str(BROKEN_REPO_DIR))
        with pytest.raises(ValueError, match="unknown source id"):
            adapters.load_gov_registry(gov_conn)
        assert (
            list_knowledge_units(gov_conn, kind=KIND, limit=10) == []
        ), "a failed load must not leave partial rows"

    def test_gov_repo_env_override(self, monkeypatch):
        adapters, _ = _mods()
        monkeypatch.setenv("FD_GOV_REPO", "/tmp/nowhere")
        assert adapters.gov_repo() == Path("/tmp/nowhere")
        monkeypatch.delenv("FD_GOV_REPO")
        assert adapters.gov_repo() == adapters.GOV_REPO
        assert adapters.GOV_REPO.name == "fd-cn-gov"


# ------------------------------------------------------------------ checkers --


CHECKER_BAD_CASES = {
    "identity-format": lambda u: _unit_with(source_name="MEE Notice!"),
    "url-https-format": lambda u: _unit_with(url="http://insecure.example.com/x/"),
    "category-vocabulary": lambda u: _unit_with(category_label="Wrong Label"),
    "organization-binding": lambda u: _unit_with(org_code="mee"),
    "column-coverage": lambda u: _unit_with(n_columns=99),
    "primary-key-exists": lambda u: _unit_with(n_primary_keys=0),
    "date-anchor-present": lambda u: _unit_with(has_date_column=False),
    "scraw-pairing": lambda u: _unit_with(scraw_url="https://elsewhere.gov.cn/"),
}


class TestGovFactCheckers:
    def test_at_least_four_checkers_registered_at_import(self):
        _mods()  # import-time registration
        names = list(checkers_for(KIND))
        assert len(names) >= 4
        assert set(CHECKER_NAMES) <= set(names)

    @pytest.mark.parametrize("name", CHECKER_NAMES)
    def test_checker_true_and_false_case(self, name, real_gov_repo):
        _mods()
        fn = checkers_for(KIND)[name]
        good = _good_unit()  # real registry truth
        assert fn(good).passed is True, f"{name} must pass on a real unit"
        result = fn(CHECKER_BAD_CASES[name](good))
        assert result.passed is False, f"{name} must fail on a mutated unit"
        assert result.detail, "checker must explain its verdict"

    def test_registration_scoped_to_the_gov_fact_kind(self):
        _mods()
        assert set(checkers_for(KIND)) == set(CHECKER_NAMES)
        assert checkers_for("definitely-no-such-kind") == {}


# --------------------------------------------------------------- run_data_eval


class TestRunDataEvalFullChain:
    def test_channel_data_run_and_criteria_rows(self, gov_conn, real_gov_repo):
        adapters, _ = _mods()
        n_units = adapters.load_gov_registry(gov_conn)
        n_checkers = len(checkers_for(KIND))

        run_id = run_data_eval(gov_conn, kind=KIND, db_path=gov_conn)

        row = gov_conn.execute(
            "SELECT rubric_name, judge_model, channel, unit_kind, score, max_score,"
            "       all_pass, n_criteria, n_passed, summary"
            " FROM eval_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert row["channel"] == "data"
        assert row["unit_kind"] == KIND
        assert row["rubric_name"] == f"data-checks:{KIND}"
        assert row["judge_model"] == "deterministic"
        assert (row["n_criteria"], row["max_score"]) == (n_units * n_checkers,) * 2
        # The real fd-cn-gov registry satisfies every deterministic contract
        # above (verified against the sibling file), so the run is an honest
        # all-pass — recorded by the checkers themselves, not claimed here.
        assert row["all_pass"] in (1, True)
        assert row["n_passed"] == row["n_criteria"]
        assert row["score"] == row["n_criteria"]
        assert row["summary"] == (
            f"deterministic data checks: {row['n_passed']}/{row['n_criteria']} passed"
        )

        crits = gov_conn.execute(
            "SELECT title, verdict FROM eval_criteria_results WHERE run_id = %s",
            (run_id,),
        ).fetchall()
        assert len(crits) == row["n_criteria"]
        assert {c["title"] for c in crits} == set(CHECKER_NAMES)
        assert all(c["verdict"] == "PASS" for c in crits)

    def test_unit_ids_selection_runs_subset(self, gov_conn, real_gov_repo):
        adapters, _ = _mods()
        adapters.load_gov_registry(gov_conn)
        key = _real_sources()[0]["name"]
        run_id = run_data_eval(gov_conn, kind=KIND, unit_ids=[key], db_path=gov_conn)
        row = gov_conn.execute(
            "SELECT n_criteria, n_passed FROM eval_runs WHERE id = %s", (run_id,)
        ).fetchone()
        assert (row["n_criteria"], row["n_passed"]) == (len(CHECKER_NAMES),) * 2

    def test_run_data_eval_unknown_unit_raises(self, gov_conn, real_gov_repo):
        adapters, _ = _mods()
        adapters.load_gov_registry(gov_conn)
        with pytest.raises(KeyError):
            run_data_eval(gov_conn, kind=KIND, unit_ids=["nope"], db_path=gov_conn)


# --------------------------------------------------- guard: no sibling writes --


def test_pack_declares_no_data_files_from_sibling_repos():
    """The pack must not reference sibling-repo paths as components (read-only)."""
    manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
    for comp in manifest["components"]:
        assert "fd-cn-gov" not in comp["path"]
        assert "fd-legal-kg" not in comp["path"]
        assert "fd-zhengxin" not in comp["path"]
        assert not comp["path"].startswith("/")


def test_upsert_roundtrip_via_record_to_unit(gov_conn, real_gov_repo):
    """record_to_unit output upserts cleanly without the loader (kernel fit)."""
    adapters, _ = _mods()
    unit = adapters.record_to_unit(adapters.read_registry_records()[0])
    stored = upsert_knowledge_unit(gov_conn, **unit)
    assert stored["kind"] == KIND
    assert stored["namespace"] == NAMESPACE
    assert stored["tier"] == "silver"
    assert stored["body"], "body must be a non-empty description"
