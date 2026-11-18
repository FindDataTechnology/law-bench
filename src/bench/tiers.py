"""Platform-level provenance-tier taxonomy and its guards (pure stdlib).

Single source of truth for:

- the four mutually-exclusive knowledge-unit tiers and their ordering,
- the bronze "never ground truth" guard and the silver "never reward
  positive" guard (single point for every loader/exporter that assembles a
  labeled sample set).

Moved verbatim from ``scripts/finetune/common.py`` so the whole platform (not
just the finetune data-prep subsystem) routes tier decisions through one
implementation. That scripts module now imports and re-exports everything
defined here, so ``from common import assert_not_ground_truth`` keeps working
with no behavior change.

This module is deliberately dependency-free (standard library only): the
scripts layer may run without the project venv, and importing it must never
require one. See ``docs/finetune-data.md`` for the tiering rationale and
``openspec/changes/add-finetune-data-flywheel/`` for the spec/design.
"""

from __future__ import annotations

from typing import Iterable

# --- tiers ------------------------------------------------------------------
# Four mutually-exclusive tiers (spec: 数据分层与溯源标记).
TIERS = ("gold", "silver", "bronze", "raw")
# Rank for "X 及以上" filter semantics. gold=0 is the highest (ground truth);
# raw=3 is the lowest (structural backbone, no label semantics).
# "silver 及以上" => records whose rank <= rank(silver), i.e. gold or silver.
TIER_RANK = {"gold": 0, "silver": 1, "bronze": 2, "raw": 3}

# --- bronze/silver guards (single point) ------------------------------------

# Ground-truth / reward-positive purposes: which tiers are forbidden for each.
# bronze (machine self-eval) is never ground truth. silver (LLM draft) is never
# a reward-positive sample (SFT warmup only). Enforced single-point here so
# every loader/exporter that assembles a labeled set routes through one check.
_GROUND_TRUTH_FLOORS = {"bronze"}          # bronze can never be ground truth
_REWARD_POSITIVE_FLOORS = {"bronze", "silver"}  # silver can never be reward positive


class TierGuardError(RuntimeError):
    """Raised when a forbidden tier is used for a guarded purpose."""


# Keep the old name as an alias so existing callers keep working.
BronzeGroundTruthError = TierGuardError


def _forbidden(tier: str, purpose: str) -> set[str]:
    """Return the tier set forbidden for ``purpose``."""
    if purpose in ("ground_truth", "judge_c_ground_truth", "drafter_a_ground_truth"):
        return _GROUND_TRUTH_FLOORS
    if purpose in ("reward_positive", "drafter_a_reward_positive"):
        return _REWARD_POSITIVE_FLOORS
    # Unknown purpose: fail closed — treat any non-gold tier as forbidden.
    return {"bronze", "silver", "raw"}


def assert_not_ground_truth(tier: str, purpose: str = "ground_truth") -> None:
    """Single-point tier guard. Call from every loader/exporter that assembles
    a ground-truth or reward-positive sample set.

    - ``purpose='ground_truth'`` (default): ``bronze`` is forbidden.
    - ``purpose='reward_positive'``: ``bronze`` and ``silver`` are forbidden.
    """
    if tier in _forbidden(tier, purpose):
        raise TierGuardError(
            f"tier={tier!r} cannot be used for purpose={purpose!r}: "
            "bronze is machine self-eval (never ground truth); "
            "silver is an LLM draft (SFT warmup only, never reward positive). "
            "See docs/finetune-data.md."
        )


def tier_at_least(tier: str, floor: str) -> bool:
    """True if ``tier``'s rank <= ``floor``'s rank (tier is at least as gold-side)."""
    return TIER_RANK[tier] <= TIER_RANK[floor]


def filter_by_tier(records: Iterable[dict], floor: str) -> list[dict]:
    """Return records whose ``tier`` is at least ``floor`` (gold side).

    Single-point tier filter used by all loaders. ``floor="gold"`` returns
    only gold; ``floor="silver"`` returns gold+silver (never bronze/raw).
    """
    return [r for r in records if tier_at_least(r.get("tier", "raw"), floor)]
