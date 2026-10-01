"""Tests for the expand-drafter-a-silver change (scripts/finetune layer).

Covers the deterministic slot-value bank (synthetic template instantiation)
and — further down — the dual-source drafter-a exporter and the
stance-stratified SFT export. Everything here is stdlib + pytest only: the
finetune scripts must run without the project venv (litellm fails to build
on some dev machines), so these tests must too.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts" / "finetune"))

import slot_value_bank as svb  # noqa: E402

WAREHOUSE_ARTIFACTS = _REPO / "data" / "finetune" / "warehouse" / "contract_artifacts.jsonl"


# ---------------------------------------------------------------------------
# exporter: dual-source build, best-run dedup, cross-source dedup (tasks 2.2-2.5)
# ---------------------------------------------------------------------------

import export_dataset as ed  # noqa: E402
import export_sft_dataset as es  # noqa: E402


class TestValidatePairCjk:
    def test_rejects_leftover_cjk_placeholder(self):
        pair = {
            "task_desc": "请起草一份买卖合同",
            "slots": [{"name": "甲方名称", "value": "某某公司"}],
            "body": "甲方：{{甲方名称}}，乙方：某某贸易公司",
            "provenance": {"annotated_by": "machine_generated", "id": "pipeline_runs:1"},
            "tier": "silver",
        }
        with pytest.raises(ed.ValidationError, match="甲方名称"):
            ed.validate_pair(pair, 0)

    def test_accepts_filled_body(self):
        pair = {
            "task_desc": "请起草一份买卖合同",
            "slots": [{"name": "甲方名称", "value": "某某公司"}],
            "body": "甲方：某某公司，乙方：某某贸易公司",
            "provenance": {"annotated_by": "machine_generated", "id": "pipeline_runs:1"},
            "tier": "silver",
        }
        ed.validate_pair(pair, 0)  # no raise


class TestBuildSilverPairs:
    def _install(self, monkeypatch, rows):
        monkeypatch.setattr(ed, "_load_warehouse_table",
                            lambda table: [{"row": r} for r in rows]
                            if table == "pipeline_runs" else [])

    def test_best_run_wins_duplicate_body(self, monkeypatch):
        body = "甲方：甲公司\n乙方：乙公司\n正文完整无占位符。"
        rows = [
            {"id": 1, "filled_text": body, "task_desc": "t",
             "score": 2, "max_score": 10, "all_pass": False, "created_at": "2026-01-01"},
            {"id": 2, "filled_text": body, "task_desc": "t",
             "score": 8, "max_score": 10, "all_pass": True, "created_at": "2026-01-02"},
        ]
        self._install(monkeypatch, rows)
        out = ed._build_silver_pairs()
        assert out["valid"] == 1
        prov = out["pairs"][0]["provenance"]
        assert prov["id"] == "pipeline_runs:2"      # the higher-scoring run
        assert prov["score_ratio"] == 0.8
        assert prov["all_pass"] is True

    def test_invalid_best_falls_to_next_run(self, monkeypatch):
        body = "甲方：甲公司\n乙方：乙公司\n正文完整。"
        rows = [
            {"id": 1, "filled_text": body, "task_desc": "",   # best score, no task_desc
             "score": 9, "max_score": 10, "created_at": "2026-01-02"},
            {"id": 2, "filled_text": body, "task_desc": "t",
             "score": 1, "max_score": 10, "created_at": "2026-01-01"},
        ]
        self._install(monkeypatch, rows)
        out = ed._build_silver_pairs()
        assert out["pairs"][0]["provenance"]["id"] == "pipeline_runs:2"
        assert out["invalid_groups"] == 0


class TestBuildSynthPairs:
    def _install(self, monkeypatch, rows):
        monkeypatch.setattr(ed, "_load_warehouse_table",
                            lambda table: [{"row": r} for r in rows]
                            if table == "contract_artifacts" else [])

    def test_instantiates_template_row(self, monkeypatch):
        rows = [{
            "id": 77, "superseded_at": None,
            "body_text": "甲方：{{甲方名称}}\n总价：{{价款金额}}",
            "slots": ["甲方名称", "价款金额"],
            "contract_type": "sale", "scenario": "农产品买卖", "stance": "pro_a",
        }]
        self._install(monkeypatch, rows)
        out = ed._build_synth_pairs()
        assert len(out["pairs"]) == 1
        p = out["pairs"][0]
        assert p["provenance"]["id"] == "contract_artifacts:77"
        assert p["provenance"]["synthetic_slots"] is True
        assert p["tier"] == "silver"
        assert "买卖合同" in p["task_desc"] and "农产品买卖" in p["task_desc"]
        assert "{{" not in p["body"]
        slot_map = {s["name"]: s["value"] for s in p["slots"]}
        assert slot_map["甲方名称"] in p["body"]  # honest-prompt rule
        assert out["dropped_mismatch"] == 0

    def test_superseded_and_mismatch_dropped(self, monkeypatch):
        rows = [
            {"id": 1, "superseded_at": "2026-08-01T00:00:00",
             "body_text": "甲方：{{甲方名称}}", "slots": ["甲方名称"]},
            {"id": 2, "superseded_at": None,
             "body_text": "甲方：{{未申报槽位}}", "slots": ["甲方名称"]},
        ]
        self._install(monkeypatch, rows)
        out = ed._build_synth_pairs()
        assert out["pairs"] == []
        assert out["skipped_superseded"] == 1
        assert out["dropped_mismatch"] == 1


class TestCrossSourceDedup:
    def test_pipeline_wins_on_identical_bodies(self, monkeypatch, tmp_path):
        # synthetic fill of {{甲方名称}} == the pipeline draft body verbatim
        body = "甲方：固定文本公司。"
        pipe_rows = [{"id": 5, "filled_text": body, "task_desc": "t",
                      "score": 5, "max_score": 10, "created_at": "2026-01-01"}]
        art_rows = [{"id": 9, "superseded_at": None,
                     "body_text": "甲方：{{甲方名称}}", "slots": ["甲方名称"],
                     "contract_type": "sale", "scenario": None, "stance": None}]
        monkeypatch.setattr(ed, "_load_warehouse_table", lambda table: (
            [{"row": r} for r in pipe_rows] if table == "pipeline_runs"
            else [{"row": r} for r in art_rows] if table == "contract_artifacts" else []))
        monkeypatch.setattr(svb, "instantiate", lambda b: (body, {"甲方名称": "固定文本公司"}, []))
        monkeypatch.setattr(ed, "DRAFTER_A_SILVER", tmp_path / "silver.jsonl")
        monkeypatch.setattr(ed, "DRAFTER_A_GOLD", tmp_path / "gold.jsonl")

        stats = ed.export_drafter_a()
        silver = json.loads((tmp_path / "silver.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert stats["silver"] == 1
        assert stats["cross_source_dropped"] == 1
        assert silver["provenance"]["id"] == "pipeline_runs:5"


class TestStratifiedSplit:
    @staticmethod
    def _rows():
        rows = [{"provenance": {"stance": "balanced"}}] * 20
        rows += [{"provenance": {"stance": "pro_a"}}] * 5
        rows += [{"provenance": {"stance": "pro_b"}}]  # single-row group
        rows += [{"provenance": {}}] * 10               # untagged
        return rows

    @staticmethod
    def _key(r):
        return (r.get("provenance") or {}).get("stance") or "(untagged)"

    def test_both_sides_per_multirow_stance(self):
        rows = self._rows()
        train, val = es._split_indices_stratified(rows, 42, 0.1, self._key)
        for stance in ("balanced", "pro_a", "(untagged)"):
            t = sum(1 for i in train if self._key(rows[i]) == stance)
            v = sum(1 for i in val if self._key(rows[i]) == stance)
            assert t >= 1 and v >= 1, f"{stance} must appear on both sides"

    def test_single_row_group_goes_to_train(self):
        rows = self._rows()
        train, val = es._split_indices_stratified(rows, 42, 0.1, self._key)
        pb = [i for i, r in enumerate(rows) if self._key(r) == "pro_b"]
        assert pb[0] in train

    def test_reproducible(self):
        rows = self._rows()
        a = es._split_indices_stratified(rows, 42, 0.1, self._key)
        b = es._split_indices_stratified(rows, 42, 0.1, self._key)
        assert a == b

    def test_partition_covers_all(self):
        rows = self._rows()
        train, val = es._split_indices_stratified(rows, 42, 0.1, self._key)
        assert train | val == set(range(len(rows)))
        assert not (train & val)


# ---------------------------------------------------------------------------
# placeholder syntax (CJK + ASCII, shared single regex)
# ---------------------------------------------------------------------------

class TestSlotRegex:
    def test_finds_cjk_names(self):
        assert sorted(svb.SLOT_RE.findall("甲方：{{甲方名称}}，总价{{总价款}}")) == [
            "总价款", "甲方名称",
        ]

    def test_finds_ascii_and_hyphenated_names(self):
        assert svb.SLOT_RE.findall("{{exchange_name}} {{party-a}}") == [
            "exchange_name", "party-a",
        ]

    def test_tolerates_inner_whitespace_and_digit_suffix(self):
        assert svb.SLOT_RE.findall("{{ 甲方名称 }} {{百分比1}}") == ["甲方名称", "百分比1"]


# ---------------------------------------------------------------------------
# determinism & completeness of instantiation
# ---------------------------------------------------------------------------

class TestInstantiate:
    BODY = (
        "甲方：{{甲方名称}}\n乙方：{{乙方名称}}\n"
        "总价：{{价款金额}}（大写：{{总价款大写}}）\n"
        "签署于{{签署日期}}，争议提交{{仲裁委员会}}仲裁。\n"
        "违约金：{{违约金}}；宽限{{天数}}天。"
    )

    def test_no_placeholder_left(self):
        filled, values, _fb = svb.instantiate(self.BODY)
        assert svb.SLOT_RE.search(filled) is None
        assert set(values) == {
            "甲方名称", "乙方名称", "价款金额", "总价款大写",
            "签署日期", "仲裁委员会", "违约金", "天数",
        }

    def test_deterministic_same_body_same_fill(self):
        f1, v1, fb1 = svb.instantiate(self.BODY)
        f2, v2, fb2 = svb.instantiate(self.BODY)
        assert f1 == f2
        assert v1 == v2
        assert fb1 == fb2

    def test_values_appear_verbatim_in_body(self):
        # honest-prompt rule: what the slots record is what the body contains
        filled, values, _fb = svb.instantiate(self.BODY)
        for name, value in values.items():
            assert value in filled

    def test_unclassifiable_name_gets_generic_filler_and_is_reported(self):
        body = "屏幕险：{{碎屏险}}；桩：{{充电桩}}"
        filled, values, fallback = svb.instantiate(body)
        assert svb.SLOT_RE.search(filled) is None
        assert set(fallback) == {"碎屏险", "充电桩"}
        # generic legal filler is drawn from the text pool
        assert values["碎屏险"] in svb.CATEGORY_POOL["text"]

    def test_digit_suffix_stem_classification(self):
        # 百分比1 / 金额2 strip their trailing digit for classification
        body = "首期{{百分比1}}，款额{{金额2}}，通知人{{通知方1}}"
        _filled, values, fallback = svb.instantiate(body)
        assert fallback == []
        assert values["百分比1"].endswith("%") or values["百分比1"] in svb.CATEGORY_POOL["percent"]
        assert values["金额2"] in svb.CATEGORY_POOL["amount"]
        assert values["通知方1"] in svb.CATEGORY_POOL["party"]


# ---------------------------------------------------------------------------
# variety: same slot name across different bodies must not collapse to one value
# ---------------------------------------------------------------------------

class TestVariety:
    def test_value_distribution_is_not_single_point(self):
        seen: set[str] = set()
        for i in range(40):
            # no f-string: {{ }} must reach the body verbatim as placeholders
            body = "乙方：{{乙方名称}}（编号 NO-" + str(i) + "）"
            _filled, values, _fb = svb.instantiate(body)
            seen.add(values["乙方名称"])
        assert len(seen) > 1, "same slot name should vary across bodies"

    def test_explicit_pools_have_min_variants(self):
        for name, pool in svb.EXPLICIT.items():
            assert len(set(pool)) >= 8, f"EXPLICIT[{name!r}] needs >=8 distinct values"

    def test_category_pools_have_min_variants(self):
        for cat, pool in svb.CATEGORY_POOL.items():
            assert len(set(pool)) >= 8, f"CATEGORY_POOL[{cat!r}] needs >=8 distinct values"


# ---------------------------------------------------------------------------
# classification spot checks
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize("name,category", [
        ("百分比1", "percent"),
        ("逾期付款违约金费率", "ratio_precise"),
        ("车架号", "code"),
        ("仲裁机构", "institution"),
        ("exchange_name", "party"),
        ("质保公里", "distance"),
        ("甲方签字", "party"),
        ("甲方印章", "seal"),
        ("乙方职务", "title"),
        ("产品等级", "grade"),
        ("监护人关系", "relation"),
        ("付款时间", "date"),
        ("总页数", "count"),
        ("标的单位", "unit"),
        ("货物体积", "volume"),
        ("未授权倍数", "multiplier"),
        ("车辆颜色内饰", "color"),
        ("注册地", None),
    ])
    def test_spot(self, name, category):
        assert svb.classify(name) == category

    def test_kw_dollar_anchor(self):
        # 月$ anchors: 期限起始月 is a month, not a duration count
        assert svb.classify("期限起始月") == "month"
        assert svb.classify("市") == "city"


# ---------------------------------------------------------------------------
# task_desc synthesis
# ---------------------------------------------------------------------------

class TestTaskDesc:
    def test_full_metadata(self):
        out = svb.synth_task_desc("sale", "农产品买卖", "pro_a")
        assert out.startswith("请起草一份买卖合同（业务场景：农产品买卖）")
        assert "立场侧重维护甲方利益" in out
        assert out.endswith("符合中国法律。")

    def test_balanced_omits_stance(self):
        out = svb.synth_task_desc("lease", "住宅租赁", "balanced")
        assert "立场" not in out
        assert "（业务场景：住宅租赁）" in out

    def test_unknown_type_falls_back_to_key(self):
        assert "unknown_type_x" in svb.synth_task_desc("unknown_type_x", None, None)

    def test_type_registry_loaded(self):
        assert len(svb.CONTRACT_TYPE_ZH) >= 60
        assert svb.CONTRACT_TYPE_ZH.get("sale") == "买卖合同"


# ---------------------------------------------------------------------------
# snapshot regression: every usable artifact row must instantiate cleanly
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not WAREHOUSE_ARTIFACTS.exists(), reason="warehouse snapshot absent")
class TestSnapshotInstantiation:
    def test_all_non_superseded_rows_instantiate(self):
        rows = [json.loads(line)["row"] for line in
                WAREHOUSE_ARTIFACTS.read_text(encoding="utf-8").splitlines() if line]
        usable = [r for r in rows if not r.get("superseded_at") and r.get("body_text")]
        assert usable, "snapshot should contain usable template rows"
        fallback_rows = 0
        for row in usable:
            filled, _values, fallback = svb.instantiate(row["body_text"])
            assert svb.SLOT_RE.search(filled) is None, (
                f"artifact {row.get('id')} still has placeholders after fill")
            if fallback:
                fallback_rows += 1
        # guardrail: fallback share must stay modest; if this trips, extend the
        # category rules rather than widening the generic filler
        assert fallback_rows / len(usable) < 0.30
