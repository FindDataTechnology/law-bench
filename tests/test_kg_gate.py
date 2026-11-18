"""Tests for the kg-gate domain pack (packs/kg-gate/).

Migrated rulers (see packs/kg-gate/README.md for the honesty map):

A. KG 车道四条硬判据 — deterministic algorithms ported from
   ``/Users/chengsishi/finddata/fd-text-core/scripts/kg_graph_checks.py``
   (+ ``kg_statute_repair_names.is_dirty_name`` / ``kg_lane.merge``). The
   live script pages FalkorDB; the migrated checkers run against imported
   graph-snapshot units. The sibling repos hold **no** exportable real
   graph-stats JSON (verified 2026-11-03), so the three snapshots under
   ``tests/fixtures/kg/`` are synthetic minimal graphs — one clean (all
   four criteria PASS), one with ①-split + ④-dirty-docno drift, one with
   ②-collapsed same-name entities. Every truth/falsehood assertion runs on
   these units; nothing claims a verdict about a production graph.

B. Market publish gate — the deterministic decision kernel of
   ``/Users/chengsishi/finddata/paas/lib/publish-tool-gate.js`` (+ registry-bridge
   surface mapping + export_surface_commercial derivation). The real gate's
   registry fetch and live probe legs stay deferred; the migrated kernel is
   the probe-absent branch of the real gate, error/note strings verbatim.
   ``TestGateDualRun`` proves zero drift by running the REAL JS gate under
   node on the same inputs (skipped honestly when node or the paas repo is
   absent — never faked).

Coverage:
- pack.yaml passes ``validate_pack`` (name/directory, real component paths);
- load idempotent across both kinds;
- each of the four KG criteria checkers has a true case and a false case
  (① split-article-zero, ② same-name separability, ③ scale reconciliation,
  ④ dirty-docno-zero), false cases driven by drift/collapsed snapshots or
  mutated copies of clean ones;
- publish gate checkers: commercial closure true/false, counts-only skip,
  existence refusal (unresolved-not-absent), full clean verdict;
- ``run_data_eval`` full chain lands channel='data' eval_runs + criteria
  rows for BOTH kinds, FAILs recorded honestly (all_pass false on drift
  fixtures, true on the clean selection).
"""

from __future__ import annotations

import copy
import importlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from src.bench.data_checks import checkers_for, run_data_eval
from src.bench.packs import load_pack, validate_pack
from src.bench.store import list_knowledge_units, upsert_knowledge_unit
from src.eval.store import ensure_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = REPO_ROOT / "packs" / "kg-gate"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "kg"
PAAS_GATE = Path("/Users/chengsishi/finddata/paas/lib/publish-tool-gate.js")

KIND_GRAPH = "graph-snapshot"
KIND_PUBLISH = "publish-rule"
NAMESPACE = "kg-gate"

GRAPH_CHECKERS = (
    "split-article-zero",
    "same-name-diff-docno-separable",
    "scale-stats-consistent",
    "dirty-docno-zero",
)
PUBLISH_CHECKERS = ("commercial-closure", "tool-declaration-gate")

CLEAN_KEY = "legal-v2-synthetic"
DRIFT_KEY = "lane-drift-synthetic"
COLLAPSED_KEY = "collapsed-samename-synthetic"


def _mods():
    """Import the pack's modules (hyphenated dir -> importlib) and return them."""
    adapters = importlib.import_module("packs.kg-gate.adapters")
    checks = importlib.import_module("packs.kg-gate.checks")
    return adapters, checks


@pytest.fixture()
def kg_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    """Per-test DB with the platform schema + kg-gate checkers registered."""
    ensure_schema(db_path=empty_db)
    _mods()  # import-time registration
    yield empty_db


def _snapshot(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _graph_unit(key: str) -> dict:
    """One snapshot as a unit dict (checker input shape), no DB round-trip."""
    snapshot = {CLEAN_KEY: "legal-v2-synthetic.json",
                DRIFT_KEY: "lane-drift-synthetic.json",
                COLLAPSED_KEY: "collapsed-samename-synthetic.json"}[key]
    _, checks = _mods()
    adapters = importlib.import_module("packs.kg-gate.adapters")
    unit = adapters.snapshot_to_unit(_snapshot(snapshot))
    return {
        "kind": unit["kind"],
        "namespace": unit["namespace"],
        "external_key": unit["external_key"],
        "body": unit["body"],
        "attrs": unit["attrs"],
    }


def _publish_unit(case: str) -> dict:
    adapters = importlib.import_module("packs.kg-gate.adapters")
    fname = {
        "law-bench-clean": "publish-rule-law-bench-clean.json",
        "internal-violation": "publish-rule-internal-violation.json",
        "counts-only-surface": "publish-rule-counts-only.json",
    }[case]
    unit = adapters.publish_rule_to_unit(_snapshot(fname))
    return {
        "kind": unit["kind"],
        "namespace": unit["namespace"],
        "external_key": unit["external_key"],
        "body": unit["body"],
        "attrs": unit["attrs"],
    }


def _mutated_unit(unit: dict, **attr_overrides) -> dict:
    u = copy.deepcopy(unit)
    u["attrs"].update(attr_overrides)
    return u


# ---------------------------------------------------------------- pack.yaml --


class TestPackManifest:
    def test_pack_yaml_validates_clean(self):
        manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
        assert manifest["name"] == "kg-gate"
        assert manifest["version"] == "0.1.0"
        assert manifest["kinds"] == [KIND_GRAPH, KIND_PUBLISH]
        assert manifest["eval_suites"] == ["kg-lane-acceptance", "market-publish-gate"]
        for comp in manifest["components"]:
            assert comp["type"] in ("module", "data", "db_seed")
            path = REPO_ROOT / comp["path"]
            assert path.is_file(), f"component path must exist: {comp['path']}"
        assert validate_pack(manifest, directory="kg-gate") == []

    def test_pack_discoverable_via_registry(self):
        manifest = load_pack("kg-gate")
        assert validate_pack(manifest, directory="kg-gate") == []

    def test_pack_declares_no_gold_judge(self):
        """kg-gate is a pure deterministic pack: no judge/calibration claim."""
        manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
        assert "gold_judge" not in manifest

    def test_pack_has_no_sibling_repo_components(self):
        """True sources live in sibling repos but nothing outside the repo is
        declared as a component (read-only discipline, like the gov pack)."""
        manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
        for comp in manifest["components"]:
            assert not comp["path"].startswith("/")
            assert "fd-text-core" not in comp["path"]
            assert "paas" not in comp["path"]


# ------------------------------------------------------------------ adapter --


class TestLoadKgGate:
    def test_load_is_idempotent(self, kg_conn):
        adapters, _ = _mods()
        n1 = adapters.load_kg_gate(kg_conn)
        n2 = adapters.load_kg_gate(kg_conn)
        assert n1 == n2 == 6  # 3 snapshots + 3 publish rules, files on disk

        graph_rows = list_knowledge_units(
            kg_conn, kind=KIND_GRAPH, namespace=NAMESPACE, limit=100
        )
        publish_rows = list_knowledge_units(
            kg_conn, kind=KIND_PUBLISH, namespace=NAMESPACE, limit=100
        )
        assert {r["external_key"] for r in graph_rows} == {
            CLEAN_KEY, DRIFT_KEY, COLLAPSED_KEY
        }
        assert {r["external_key"] for r in publish_rows} == {
            "law-bench-clean", "internal-violation", "counts-only-surface"
        }
        # Synthetic demo data: tiered honestly as bronze, never silver/gold.
        assert all(r["tier"] == "bronze" for r in graph_rows + publish_rows)
        assert all(r["body"] for r in graph_rows + publish_rows)
        for r in graph_rows:
            assert r["provenance"]["true_source"].endswith("kg_graph_checks.py")
            assert r["tags"]["source"] == "synthetic"

    def test_load_raises_when_fixtures_dir_missing(self, kg_conn, monkeypatch, tmp_path):
        adapters, _ = _mods()
        monkeypatch.setenv("KG_GATE_FIXTURES", str(tmp_path / "nowhere"))
        with pytest.raises(FileNotFoundError):
            adapters.load_kg_gate(kg_conn)

    def test_snapshot_loader_rejects_dangling_edge(self):
        """A snapshot edge pointing at an unknown uuid is file corruption:
        the mapper raises, it does not become a unit-level FAIL."""
        adapters, _ = _mods()
        broken = _snapshot("legal-v2-synthetic.json")
        broken["edges"].append({"src": "u1", "dst": "nope", "type": "CITES"})
        with pytest.raises(ValueError, match="unknown node"):
            adapters.snapshot_to_unit(broken)

    def test_publish_mapper_rejects_missing_sections(self):
        adapters, _ = _mods()
        with pytest.raises(ValueError, match="pack_manifest"):
            adapters.publish_rule_to_unit({"case": "x", "registry_index": {}})

    def test_unit_kwargs_upsert_cleanly(self, kg_conn):
        """record→unit output upserts without the loader (kernel fit)."""
        adapters, _ = _mods()
        unit = adapters.snapshot_to_unit(_snapshot("legal-v2-synthetic.json"))
        stored = upsert_knowledge_unit(kg_conn, **unit)
        assert stored["kind"] == KIND_GRAPH
        assert stored["namespace"] == NAMESPACE
        assert stored["attrs"]["summary"]["nodes"] == 6


# ---------------------------------------------------------------- KG checkers --


class TestKGLaneCheckers:
    def test_four_checkers_registered_at_import(self):
        _mods()
        assert list(checkers_for(KIND_GRAPH)) == list(GRAPH_CHECKERS)
        assert set(checkers_for(KIND_PUBLISH)) == set(PUBLISH_CHECKERS)

    # 判据① —— 条级分裂节点清零
    def test_criterion_one_split_article_true_and_false(self):
        _mods()
        fn = checkers_for(KIND_GRAPH)["split-article-zero"]
        assert fn(_graph_unit(CLEAN_KEY)).passed is True
        bad = fn(_graph_unit(DRIFT_KEY))
        assert bad.passed is False
        assert "中华人民共和国合同法第四百二十四条" in bad.detail

    # 判据④ —— 脏文号清零
    def test_criterion_four_dirty_docno_true_and_false(self):
        _mods()
        fn = checkers_for(KIND_GRAPH)["dirty-docno-zero"]
        assert fn(_graph_unit(CLEAN_KEY)).passed is True
        bad = fn(_graph_unit(DRIFT_KEY))
        assert bad.passed is False
        assert "财政部中华人民共和国财政部令第71号" in bad.detail

    # 判据② —— 同名不同文号可分（113/71）
    def test_criterion_two_same_name_separable_true_and_false(self):
        _mods()
        fn = checkers_for(KIND_GRAPH)["same-name-diff-docno-separable"]
        good = fn(_graph_unit(CLEAN_KEY))
        assert good.passed is True
        # the clean snapshot carries the 113/71 pair the original printed
        assert "行政单位财务规则" in good.detail
        bad = fn(_graph_unit(COLLAPSED_KEY))
        assert bad.passed is False
        assert "坍缩" in bad.detail

    def test_criterion_two_requires_distinct_docnos_in_same_base_group(self):
        """Synthetic guard: same base, both carry the SAME docno -> not 可分."""
        _mods()
        fn = checkers_for(KIND_GRAPH)["same-name-diff-docno-separable"]
        unit = _graph_unit(COLLAPSED_KEY)
        unit["attrs"]["nodes"] = [
            {"uuid": "x1", "name": "行政单位财务规则（财政部令第71号）"},
            {"uuid": "x2", "name": "行政单位财务规则（财政部令第71号）"},
        ]
        assert fn(unit).passed is False  # duplicate identical names

        unit2 = copy.deepcopy(unit)
        unit2["attrs"]["nodes"] = [
            {"uuid": "x1", "name": "行政单位财务规则（财政部令第71号）"},
            {"uuid": "x2", "name": "行政单位财务规则（财政部令第113号）"},
        ]
        assert fn(unit2).passed is True  # the honest 113/71 shape

    # 判据③ —— 规模统计对账
    def test_criterion_three_scale_stats_true_and_false(self):
        _mods()
        fn = checkers_for(KIND_GRAPH)["scale-stats-consistent"]
        for key in (CLEAN_KEY, DRIFT_KEY, COLLAPSED_KEY):
            assert fn(_graph_unit(key)).passed is True, f"{key} is summary-consistent"
        bad = fn(_mutated_unit(_graph_unit(CLEAN_KEY), summary={
            "nodes": 999, "edges": 3, "statute_layer_nodes": 5,
        }))
        assert bad.passed is False
        assert "nodes=6" in bad.detail


# ----------------------------------------------------------- publish checkers --


class TestPublishGateCheckers:
    def test_commercial_closure_true_and_false(self):
        _mods()
        fn = checkers_for(KIND_PUBLISH)["commercial-closure"]
        assert fn(_publish_unit("law-bench-clean")).passed is True

        bad = fn(_publish_unit("internal-violation"))
        assert bad.passed is False
        # names the offending tool exactly like the real gate's message
        assert (
            "MCP server 'law-bench' is surface-registered; tools outside its "
            "commercial set may not enter a pack: admin_purge"
        ) in bad.detail

    def test_commercial_closure_counts_only_skips_with_note(self):
        """pre-enrichment shape: closure skipped, observable note, not a guess."""
        _mods()
        fn = checkers_for(KIND_PUBLISH)["commercial-closure"]
        res = fn(_publish_unit("counts-only-surface"))
        assert res.passed is True
        assert "closure skipped" in res.detail

    def test_gate_full_verdict_clean_passes(self):
        _mods()
        fn = checkers_for(KIND_PUBLISH)["tool-declaration-gate"]
        assert fn(_publish_unit("law-bench-clean")).passed is True

    def test_gate_existence_leg_refuses_unresolved_not_absent(self):
        """Declared name missing from the tool_list snapshot: the probe leg is
        deferred, so the migrated kernel reproduces the real gate's
        probe-absent branch verbatim (actionable refusal, never 'absent')."""
        _mods()
        fn = checkers_for(KIND_PUBLISH)["tool-declaration-gate"]
        unit = _publish_unit("law-bench-clean")
        index = unit["attrs"]["registry_index"]
        index["law-bench"]["tool_list"] = ["clause_search", "verify_contract"]
        bad = fn(_mutated_unit(unit, registry_index=index))
        assert bad.passed is False
        assert "unresolved rather than absent" in bad.detail
        assert "contract_draft" in bad.detail
        assert "does not expose" not in bad.detail  # never asserts absence

    def test_gate_local_binding_reference_is_exempt(self):
        _mods()
        fn = checkers_for(KIND_PUBLISH)["tool-declaration-gate"]
        unit = _publish_unit("law-bench-clean")
        manifest = unit["attrs"]["pack_manifest"]
        manifest["mcpServers"][0]["registryName"] = "my-private-mcp"
        res = fn(_mutated_unit(unit, pack_manifest=manifest))
        assert res.passed is True
        assert "local binding contract" in res.detail

    def test_gate_tool_face_leg(self):
        """Reference declaring neither allowTools nor fullSurface fails the
        face leg (pure publish check, ported)."""
        _, checks = _mods()
        manifest = {
            "name": "faceless-pack",
            "mcpServers": [{"registryName": "law-bench", "allowTools": []}],
        }
        errs = checks.tool_face_errors(manifest)
        assert len(errs) == 1
        assert "declares no tool face" in errs[0]["error"]

    def test_skill_tool_closure_leg(self):
        """A skill naming a tool outside the reference's allowTools fails the
        tool-level closure leg (ported from toolClosureErrors)."""
        _, checks = _mods()
        manifest = {
            "name": "sneaky-pack",
            "mcpServers": [{"registryName": "law-bench", "allowTools": ["read"]}],
            "skills": [{"name": "s1", "content": "use mcp__law-bench__purge_all here"}],
        }
        errs = checks.tool_closure_errors(manifest)
        assert len(errs) == 1
        assert "purge_all" in errs[0]["error"]
        assert "outside that reference's allowTools" in errs[0]["error"]

    def test_commercial_set_derivation_from_manifest(self):
        """export_surface_commercial.commercial_tools ported: group-level and
        per-tool levels alike; conflicts raise, order sorted."""
        _, checks = _mods()
        manifest = {
            "tool_groups": [
                {"group": "core", "level": "commercial", "tools": ["b_tool", "a_tool"]},
                {"group": "ops", "level": "internal",
                 "tools": [{"name": "c_tool", "level": "commercial"}, "d_tool"]},
            ]
        }
        assert checks.commercial_tools(manifest) == ["a_tool", "b_tool", "c_tool"]
        with pytest.raises(ValueError, match="conflicting levels"):
            checks.commercial_tools({"tool_groups": [
                {"group": "g1", "level": "commercial", "tools": ["t"]},
                {"group": "g2", "level": "internal", "tools": ["t"]},
            ]})


# --------------------------------------------------------------- run_data_eval


class TestRunDataEvalFullChain:
    def test_graph_kind_channels_data_and_records_honest_fails(self, kg_conn):
        adapters, _ = _mods()
        n_units = 3
        assert adapters.load_kg_gate(kg_conn) == 6

        run_id = run_data_eval(kg_conn, kind=KIND_GRAPH, db_path=kg_conn)
        row = kg_conn.execute(
            "SELECT rubric_name, judge_model, channel, unit_kind, score, max_score,"
            "       all_pass, n_criteria, n_passed, summary"
            " FROM eval_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        assert row["channel"] == "data"
        assert row["unit_kind"] == KIND_GRAPH
        assert row["rubric_name"] == f"data-checks:{KIND_GRAPH}"
        assert row["judge_model"] == "deterministic"
        assert row["n_criteria"] == n_units * len(GRAPH_CHECKERS)
        # Honest aggregation: clean snapshot passes 4/4; the drift snapshot
        # fails ① + ④; the collapsed snapshot fails ② — FAILs are recorded,
        # not washed green. all_pass must therefore be false.
        assert row["n_passed"] == 4 + 2 + 3
        assert row["score"] == row["n_passed"]
        assert row["all_pass"] in (0, False)

        crits = kg_conn.execute(
            "SELECT criterion_id, title, verdict"
            " FROM eval_criteria_results WHERE run_id = %s",
            (run_id,),
        ).fetchall()
        assert len(crits) == row["n_criteria"]
        fails = [c for c in crits if c["verdict"] == "FAIL"]
        assert {c["title"] for c in fails} == {
            "split-article-zero", "dirty-docno-zero",
            "same-name-diff-docno-separable",
        }
        assert len(fails) == 3
        assert all(c["criterion_id"].startswith(f"{NAMESPACE}/") for c in crits)

    def test_publish_kind_channels_data(self, kg_conn):
        adapters, _ = _mods()
        adapters.load_kg_gate(kg_conn)

        run_id = run_data_eval(kg_conn, kind=KIND_PUBLISH, db_path=kg_conn)
        row = kg_conn.execute(
            "SELECT channel, unit_kind, n_criteria, n_passed, all_pass"
            " FROM eval_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        assert row["channel"] == "data"
        assert row["unit_kind"] == KIND_PUBLISH
        assert row["n_criteria"] == 3 * len(PUBLISH_CHECKERS)
        # clean 2/2, counts-only 2/2, internal-violation 0/2 (both legs refuse)
        assert row["n_passed"] == 4
        assert row["all_pass"] in (0, False)

    def test_clean_selection_all_passes(self, kg_conn):
        """The clean snapshot alone is an honest all-pass run."""
        adapters, _ = _mods()
        adapters.load_kg_gate(kg_conn)
        run_id = run_data_eval(
            kg_conn, kind=KIND_GRAPH, unit_ids=[CLEAN_KEY], db_path=kg_conn
        )
        row = kg_conn.execute(
            "SELECT n_criteria, n_passed, all_pass FROM eval_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        assert row["n_criteria"] == len(GRAPH_CHECKERS)
        assert row["n_passed"] == len(GRAPH_CHECKERS)
        assert row["all_pass"] in (1, True)


# ------------------------------------------------- dual run against the JS gate


_HARNESS = """\
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const gate = await import(pathToFileURL(process.argv[2]).href);
const { manifest, index } = JSON.parse(readFileSync(process.argv[3], "utf8"));

// Mirror of paas/registry-bridge.js: toolListNames + the metadata.surface
// mapping (commercial_tools name list wins; the pre-enrichment counts-only
// shape becomes the "counts-only" sentinel the gate understands).
function toolListNames(toolList) {
  if (!Array.isArray(toolList)) return null;
  const names = [];
  for (const t of toolList) {
    if (typeof t === "string") names.push(t);
    else if (t && typeof t === "object" && typeof t.name === "string") names.push(t.name);
  }
  return names.length ? names : null;
}
function serverInfo(name) {
  const s = index[name];
  if (!s) return null;
  const surface = s.metadata?.surface;
  let commercialTools = null;
  if (Array.isArray(surface?.commercial_tools)) {
    commercialTools = surface.commercial_tools.map((t) => String(t));
  } else if (surface && Number.isFinite(Number(surface.tools_commercial))) {
    commercialTools = "counts-only";
  }
  return { toolList: toolListNames(s.tool_list), commercialTools, endpoint: null };
}

const { errors, notes } = await gate.toolGateErrors(manifest, serverInfo, {});
const out = {
  declared: [...gate.declaredToolsByServer(manifest)].map(([s, set]) => [s, [...set]]),
  face: gate.toolFaceErrors(manifest),
  closure: gate.toolClosureErrors(manifest),
  errors,
  notes,
};
process.stdout.write(JSON.stringify(out));
"""


def _py_gate_view(checks, manifest, index):
    def server_info(name):
        entry = index.get(name)
        return checks.server_info_from_entry(entry) if entry is not None else None

    errors, notes = checks.tool_gate_errors(manifest, server_info)
    return {
        "declared": [[s, names] for s, names in checks.declared_tools_by_server(manifest).items()],
        "face": checks.tool_face_errors(manifest),
        "closure": checks.tool_closure_errors(manifest),
        "errors": errors,
        "notes": notes,
    }


def _js_gate_view(tmp_path, manifest, index):
    harness = tmp_path / "gate-harness.mjs"
    harness.write_text(_HARNESS, encoding="utf-8")
    payload = tmp_path / "input.json"
    payload.write_text(json.dumps({"manifest": manifest, "index": index}), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(harness), str(PAAS_GATE), str(payload)],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"node harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


@pytest.mark.skipif(
    not shutil.which("node") or not PAAS_GATE.is_file(),
    reason="dual run needs node + the read-only paas repo "
           "(neither faked: the check skips, it never asserts drift)",
)
class TestGateDualRun:
    """Zero-drift proof: the migrated kernel vs the REAL publish-tool-gate.js
    on identical inputs (no probe passed — the offline branch; zero network)."""

    @pytest.mark.parametrize("case", [
        "law-bench-clean", "internal-violation", "counts-only-surface",
    ])
    def test_fixtures_agree_with_the_real_gate(self, tmp_path, case):
        _, checks = _mods()
        unit = _publish_unit(case)
        manifest = unit["attrs"]["pack_manifest"]
        index = unit["attrs"]["registry_index"]
        assert _py_gate_view(checks, manifest, index) == _js_gate_view(tmp_path, manifest, index)

    def test_existence_leg_agrees(self, tmp_path):
        _, checks = _mods()
        unit = _publish_unit("law-bench-clean")
        manifest = unit["attrs"]["pack_manifest"]
        index = copy.deepcopy(unit["attrs"]["registry_index"])
        index["law-bench"]["tool_list"] = ["clause_search", "verify_contract"]
        view = _py_gate_view(checks, manifest, index)
        assert view == _js_gate_view(tmp_path, manifest, index), view["errors"]
        assert view["errors"], "the drifted tool_list must be refused, not passed"

    def test_local_exempt_and_face_legs_agree(self, tmp_path):
        _, checks = _mods()
        manifest = {
            "name": "dual-pack",
            "mcpServers": [
                {"registryName": "my-private-mcp", "allowTools": ["whatever"]},
                {"registryName": "law-bench"},
            ],
            "agents": [],
            "skills": [
                {"name": "s", "content": "mcp__law-bench__contract_draft and mcp__x__y__z"},
            ],
        }
        index = {}  # nothing is a registry entry
        assert _py_gate_view(checks, manifest, index) == _js_gate_view(tmp_path, manifest, index)
