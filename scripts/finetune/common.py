#!/usr/bin/env python3
"""Shared constants & helpers for the finetune data-prep subsystem.

Single source of truth for:

- the open-source license allowlist + gate,
- manifest record shape, paths, and deterministic JSONL I/O.

The four-tier taxonomy and its guards moved verbatim to the platform kernel
(``src/bench/tiers.py``) and are re-exported below unchanged, so sibling
scripts' ``from common import ...`` (tier names included) keeps working with a
single implementation.

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
import sys

# Kernel import: put the repo root (common.py -> parents[2]) on sys.path so
# ``src.bench.tiers`` resolves even when the scripts layer runs without the
# project venv — tiers.py is pure stdlib, so the import never needs one. The
# tier API below is a re-export of that single source; there is no second copy.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from src.bench.tiers import (  # noqa: E402,F401  (re-exported; single source)
    TIERS,
    TIER_RANK,
    BronzeGroundTruthError,
    TierGuardError,
    assert_not_ground_truth,
    filter_by_tier,
    tier_at_least,
)

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

# --- tier map for warehouse extraction (tier system: src/bench/tiers.py) ----
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
