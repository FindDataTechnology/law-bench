"""Tests for the platform-level tier kernel (``src/bench/tiers.py``).

Pins the semantics moved verbatim from ``scripts/finetune/common.py``:

- the bronze "never ground truth" guard and the silver "never reward
  positive" guard, including the shared purpose aliases and the fail-closed
  unknown-purpose branch,
- the exact rank direction (gold=0 highest) and ``filter_by_tier`` floor
  semantics (including the unlabeled-record default),
- the byte-identical guard error text,
- the kernel module staying pure stdlib, and
- ``scripts/finetune/common.py`` re-exporting the kernel's objects themselves
  (single source of truth, no second implementation).
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

from src.bench.tiers import (
    TIERS,
    TIER_RANK,
    BronzeGroundTruthError,
    TierGuardError,
    assert_not_ground_truth,
    filter_by_tier,
    tier_at_least,
)


class TestTierGuards:
    def test_bronze_rejected_as_ground_truth(self):
        with pytest.raises(TierGuardError) as excinfo:
            assert_not_ground_truth("bronze")
        assert "tier='bronze'" in str(excinfo.value)
        assert "purpose='ground_truth'" in str(excinfo.value)

    def test_silver_rejected_as_reward_positive(self):
        with pytest.raises(TierGuardError):
            assert_not_ground_truth("silver", purpose="reward_positive")

    def test_bronze_rejected_as_reward_positive_too(self):
        with pytest.raises(TierGuardError):
            assert_not_ground_truth("bronze", purpose="reward_positive")

    @pytest.mark.parametrize("tier", ["gold", "raw"])
    def test_compliant_ground_truth_paths(self, tier):
        # raw is the lowest tier but carries no label semantics, so it is a
        # legal ground-truth carrier as far as the guard is concerned.
        assert_not_ground_truth(tier, purpose="ground_truth")  # no raise

    @pytest.mark.parametrize("tier", ["gold", "raw"])
    def test_compliant_reward_positive_paths(self, tier):
        assert_not_ground_truth(tier, purpose="reward_positive")  # no raise

    def test_silver_is_a_legal_ground_truth_carrier(self):
        # Only bronze is barred from ground truth; silver (LLM draft) may be.
        assert_not_ground_truth("silver", purpose="ground_truth")  # no raise

    def test_purpose_aliases_share_the_same_floors(self):
        with pytest.raises(TierGuardError):
            assert_not_ground_truth("bronze", purpose="judge_c_ground_truth")
        with pytest.raises(TierGuardError):
            assert_not_ground_truth("bronze", purpose="drafter_a_ground_truth")
        with pytest.raises(TierGuardError):
            assert_not_ground_truth("silver", purpose="drafter_a_reward_positive")
        # silver is fine as drafter/judge-c ground truth input.
        assert_not_ground_truth("silver", purpose="drafter_a_ground_truth")

    @pytest.mark.parametrize("tier", TIERS)
    def test_unknown_purpose_fails_closed(self, tier):
        # Any purpose the guard does not know treats every non-gold tier as
        # forbidden; gold is always the safe carrier.
        if tier == "gold":
            assert_not_ground_truth(tier, purpose="mystery-purpose")  # no raise
        else:
            with pytest.raises(TierGuardError):
                assert_not_ground_truth(tier, purpose="mystery-purpose")

    def test_error_text_is_byte_identical_to_the_original(self):
        with pytest.raises(TierGuardError) as excinfo:
            assert_not_ground_truth("bronze", purpose="ground_truth")
        assert str(excinfo.value) == (
            "tier='bronze' cannot be used for purpose='ground_truth': "
            "bronze is machine self-eval (never ground truth); "
            "silver is an LLM draft (SFT warmup only, never reward positive). "
            "See docs/finetune-data.md."
        )

    def test_legacy_alias_is_the_same_class(self):
        assert BronzeGroundTruthError is TierGuardError

    def test_guard_error_is_a_runtime_error(self):
        assert issubclass(TierGuardError, RuntimeError)


class TestRankAndFilter:
    def test_tier_rank_definition_and_direction(self):
        # gold=0 is the highest (ground truth); raw=3 the lowest.
        assert TIER_RANK == {"gold": 0, "silver": 1, "bronze": 2, "raw": 3}
        assert TIERS == ("gold", "silver", "bronze", "raw")

    @pytest.mark.parametrize(
        ("tier", "floor", "expected"),
        [
            ("gold", "gold", True),
            ("gold", "silver", True),
            ("gold", "bronze", True),
            ("gold", "raw", True),
            ("silver", "gold", False),
            ("silver", "silver", True),
            ("bronze", "silver", False),
            ("bronze", "bronze", True),
            ("raw", "bronze", False),
            ("raw", "raw", True),
        ],
    )
    def test_tier_at_least(self, tier, floor, expected):
        assert tier_at_least(tier, floor) is expected

    def test_tier_at_least_unknown_tier_raises(self):
        with pytest.raises(KeyError):
            tier_at_least("diamond", "gold")

    _RECORDS = [
        {"tier": "gold", "i": 0},
        {"tier": "silver", "i": 1},
        {"tier": "bronze", "i": 2},
        {"tier": "raw", "i": 3},
    ]

    def test_filter_floor_gold_keeps_only_gold(self):
        assert filter_by_tier(self._RECORDS, "gold") == [{"tier": "gold", "i": 0}]

    def test_filter_floor_silver_keeps_gold_and_silver(self):
        assert filter_by_tier(self._RECORDS, "silver") == self._RECORDS[:2]

    def test_filter_floor_raw_keeps_everything(self):
        assert filter_by_tier(self._RECORDS, "raw") == self._RECORDS

    def test_filter_missing_tier_defaults_to_raw(self):
        # Original semantics: r.get("tier", "raw") — unlabeled records rank as
        # the lowest tier and only survive floor="raw".
        records = [{"n": 1}, {"n": 2, "tier": "gold"}]
        assert filter_by_tier(records, "raw") == records
        assert filter_by_tier(records, "gold") == [{"n": 2, "tier": "gold"}]

    def test_filter_preserves_order_and_object_identity(self):
        out = filter_by_tier(self._RECORDS, "silver")
        assert out[0] is self._RECORDS[0]
        assert out[1] is self._RECORDS[1]

    def test_filter_accepts_any_iterable(self):
        gen = (r for r in self._RECORDS)
        assert len(filter_by_tier(gen, "gold")) == 1


class TestKernelHygiene:
    def test_tiers_module_imports_stdlib_only(self):
        # The scripts layer must be able to import this module without the
        # project venv — pin it as a hard regression gate.
        kernel = (
            pathlib.Path(__file__).resolve().parents[1] / "src" / "bench" / "tiers.py"
        )
        tree = ast.parse(kernel.read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    roots.add("<relative>")
                elif node.module:
                    roots.add(node.module.split(".")[0])
        roots.discard("src")  # kernel-internal absolute import (src.bench.*)
        allowed = set(sys.stdlib_module_names) | {"__future__"}
        assert roots <= allowed, f"non-stdlib imports crept in: {sorted(roots - allowed)}"


class TestSingleSourceReexport:
    def test_common_reexports_the_kernel_objects_themselves(self):
        repo = pathlib.Path(__file__).resolve().parents[1]
        scripts_dir = str(repo / "scripts" / "finetune")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import common

        import src.bench.tiers as kernel_tiers

        assert common.assert_not_ground_truth is kernel_tiers.assert_not_ground_truth
        assert common.filter_by_tier is kernel_tiers.filter_by_tier
        assert common.tier_at_least is kernel_tiers.tier_at_least
        assert common.TierGuardError is kernel_tiers.TierGuardError
        assert common.BronzeGroundTruthError is kernel_tiers.BronzeGroundTruthError
        assert common.TIER_RANK is kernel_tiers.TIER_RANK
        assert common.TIERS is kernel_tiers.TIERS

    def test_common_tier_map_still_targets_valid_tiers(self):
        # TIER_BY_TABLE stayed in the scripts layer (it is domain-specific)
        # but every value must be a tier the kernel knows.
        repo = pathlib.Path(__file__).resolve().parents[1]
        scripts_dir = str(repo / "scripts" / "finetune")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import common

        assert set(common.TIER_BY_TABLE.values()) <= set(TIERS)
