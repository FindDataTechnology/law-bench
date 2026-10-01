#!/usr/bin/env python3
"""Shared constants & helpers for the finetune data-prep subsystem.

Single source of truth for:

- the four mutually-exclusive tiers and their ordering,
- the bronze "never ground truth" guard (single point),
- the open-source license allowlist + gate,
- manifest record shape, paths, and deterministic JSONL I/O.

See ``docs/finetune-data.md`` for the tiering rationale and
``openspec/changes/add-finetune-data-flywheel/`` for the spec/design.

This module is importable both locally (export/validate scripts) and inside
the law-bench pod (warehouse extraction reuses its tier map). Sibling scripts
put their own directory on ``sys.path`` and ``from common import ...``.
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Iterable

# --- slot placeholder syntax (single point for the scripts layer) -----------
# Mirrors src/generator/slots.py SLOT_PATTERN: {{name}} with optional inner
# whitespace; the name is CJK/ASCII word chars plus '-'. The scripts layer
# cannot import src.* (project venv may be unavailable), so the pattern is
# restated here and kept in sync manually. The old ASCII-only regex missed
# {{甲方名称}} placeholders entirely.
SLOT_RE = re.compile(r"\{\{\s*([\w][\w-]*)\s*\}\}")

# --- layout -----------------------------------------------------------------
FINETUNE_ROOT = pathlib.Path("data/finetune")
WAREHOUSE_DIR = FINETUNE_ROOT / "warehouse"
OPENSOURCE_DIR = FINETUNE_ROOT / "opensource"
JUDGE_C_DIR = FINETUNE_ROOT / "judge-c"
DRAFTER_A_DIR = FINETUNE_ROOT / "drafter-a"
MANIFEST_DIR = FINETUNE_ROOT / "manifests"

MANIFEST_SCHEMA_PATH = MANIFEST_DIR / "manifest.schema.json"
WAREHOUSE_MANIFEST = MANIFEST_DIR / "warehouse_manifest.jsonl"
REJECTED_SOURCES = MANIFEST_DIR / "rejected_sources.jsonl"
COVERAGE_GAPS = MANIFEST_DIR / "coverage_gaps.jsonl"

# --- tiers ------------------------------------------------------------------
# Four mutually-exclusive tiers (spec: 数据分层与溯源标记).
TIERS = ("gold", "silver", "bronze", "raw")
# Rank for "X 及以上" filter semantics. gold=0 is the highest (ground truth);
# raw=3 is the lowest (structural backbone, no label semantics).
# "silver 及以上" => records whose rank <= rank(silver), i.e. gold or silver.
TIER_RANK = {"gold": 0, "silver": 1, "bronze": 2, "raw": 3}

# Which warehouse table maps to which tier at extraction time. The extractor
# tags each material with the tier from this map.
TIER_BY_TABLE = {
    "clauses": "raw",  # structural backbone + judge input pool
    "pipeline_runs": "silver",  # LLM filled_text draft; SFT warmup ONLY
    "eval_runs": "raw",  # run-level envelope; no per-criterion label
    "eval_criteria_results": "bronze",  # machine self-eval; NEVER ground truth
    "rubrics": "gold",  # human rubric
    "criteria": "gold",  # human criteria
    # widen: expand-finetune-data-sources §1.1
    "type_validations": "gold",  # compliance rules w/ law_ref; judge-c criteria scaffold
    "law_info": "bronze",  # LLM-generated law summaries; retrieval aid, never ground truth
    "contract_artifacts": "raw",  # template bodies w/ {{slot}}; drafter skeleton, no labels
    "core_clauses": "gold",  # mandatory-clause checklist per type
    "industry_standard_references": "gold",  # statute pointers per type
}

# --- bronze/silver guards (single point) -----------------------------------

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


# --- license gate -----------------------------------------------------------
LICENSE_ALLOWLIST = {"Apache-2.0", "MIT"}


class LicenseRejectedError(RuntimeError):
    """A candidate open-source corpus was rejected by the license gate."""


def check_license(license_text: str | None, source: str) -> str:
    """Return the matched SPDX id from the allowlist, or raise.

    String-matches the candidate corpus ``LICENSE`` body. Non-allowlisted or
    missing licenses are rejected at the intake layer (spec: 开源语料许可证闸门).
    The allowlist only ever loosens; tightening needs a separate change.
    """
    if not license_text:
        raise LicenseRejectedError(f"{source}: 缺少许可证声明")
    body = license_text
    if "Apache License" in body or "SPDX-License-Identifier: Apache-2.0" in body:
        return "Apache-2.0"
    if "MIT License" in body or "SPDX-License-Identifier: MIT" in body:
        return "MIT"
    raise LicenseRejectedError(
        f"{source}: 许可证不在白名单 {sorted(LICENSE_ALLOWLIST)} 中"
    )


# --- manifest I/O (deterministic for idempotency) --------------------------


def dumps_record(record: dict) -> str:
    """Deterministic single-line JSON for one manifest/material record.

    ``sort_keys=True`` + fixed separators => same record always serializes to
    the same bytes, so re-running an extractor over the same DB yields a
    byte-identical file (spec: 幂等只读抽取).
    """
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_jsonl(path: pathlib.Path, records: list[dict]) -> None:
    """Write records as deterministic JSONL (sorted keys, no trailing spaces)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [dumps_record(r) for r in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_jsonl(path: pathlib.Path) -> list[dict]:
    """Read a JSONL file into a list of dicts (empty list if absent)."""
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def append_jsonl(path: pathlib.Path, records: list[dict]) -> None:
    """Append records to a JSONL file (used for rejection/gap logs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(dumps_record(r) + "\n")
