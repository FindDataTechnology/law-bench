"""Domain-pack ruler equivalence (change add-knowledge-bench-platform, task 4.6).

"迁入的尺子与原仓对同输入双跑零漂移": the finance pack derived a band->direction
ruler; the origin of that ruler is fd-sentiment's ``evaluate._BAND_SIGN``. This
test double-runs both mappings over every band and over the real gold-v9 items
(read-only from the sibling repo) and asserts zero drift. When the sibling
checkout is absent (e.g. public CI) the run narrows to the band-space check and
skips the gold-items leg with an explicit reason - never a fake green.

Scope honestly recorded in tasks.md: the gov pack's checkers are a distillation
of the KG hard criteria (identity/scale/dirty-number semantics), not a 1:1
re-host of a double-runnable scorer (the original needs live FalkorDB), so no
equivalence assertion applies there yet.
"""

from __future__ import annotations

import importlib
import json
import os
import re
from pathlib import Path

import pytest

# hyphenated pack dir -> importlib (the "from packs.finance-data..." grammar is
# invalid Python); mirrors tests/test_finance_data_pack.py.
_adapters = importlib.import_module("packs.finance-data.adapters")
_checks = importlib.import_module("packs.finance-data.checks")
BAND_TO_DIRECTION = _adapters.BAND_TO_DIRECTION
check_band_direction_consistency = _checks.check_band_direction_consistency

# 这个测试要读 sibling repo 的源码，而 sibling 不在本仓。没有路径时跳过并说明，
# 不假装通过——「没有输入时判通过」的闸比没有闸更糟。
_SENTIMENT_ENV = os.environ.get("FD_SENTIMENT_REPO")
SENTIMENT_REPO = Path(_SENTIMENT_ENV) if _SENTIMENT_ENV else None

pytestmark = pytest.mark.skipif(
    SENTIMENT_REPO is None or not SENTIMENT_REPO.is_dir(),
    reason="FD_SENTIMENT_REPO not set or missing — this suite compares against the sibling repo",
)
BANDS = ("strong_bullish", "bullish", "neutral", "bearish", "strong_bearish")


def _origin_band_sign() -> dict[str, int]:
    """Parse _BAND_SIGN out of fd-sentiment/evaluate.py WITHOUT importing it
    (sibling repo is not a dependency; read-only extraction of the dict)."""
    src = (SENTIMENT_REPO / "fd_sentiment" / "evaluate.py").read_text(encoding="utf-8")
    m = re.search(r"_BAND_SIGN\s*=\s*\{([^}]*)\}", src)
    assert m, "_BAND_SIGN not found in fd-sentiment/evaluate.py"
    return {k: int(v) for k, v in re.findall(r'"(\w+)":\s*(-?\d+)', m.group(1))}


def _sign_to_direction(sign: int) -> str:
    return {1: "bullish", 0: "neutral", -1: "bearish"}[sign]


def test_band_mapping_zero_drift_vs_origin():
    if not (SENTIMENT_REPO / "fd_sentiment" / "evaluate.py").is_file():
        pytest.skip(f"fd-sentiment checkout absent at {SENTIMENT_REPO} - origin ruler not readable here")
    origin = _origin_band_sign()
    assert set(origin) == set(BANDS), "origin band set drifted"
    mismatches = [
        f"{b}: mine={BAND_TO_DIRECTION[b]!r} origin={_sign_to_direction(origin[b])!r}"
        for b in BANDS
        if BAND_TO_DIRECTION[b] != _sign_to_direction(origin[b])
    ]
    assert mismatches == [], "direction ruler drift:\n" + "\n".join(mismatches)


def test_gold_v9_items_double_run_zero_drift():
    gold_file = SENTIMENT_REPO / "gold" / "gold-v9.json"
    if not gold_file.is_file():
        pytest.skip("fd-sentiment checkout absent - gold-items leg not runnable here")
    origin = _origin_band_sign()
    items = json.loads(gold_file.read_text(encoding="utf-8"))["items"]
    assert len(items) > 0, "gold-v9 has no items"
    drift = [
        it["doc_id"]
        for it in items
        if BAND_TO_DIRECTION.get(it["expected_band"]) != _sign_to_direction(origin.get(it["expected_band"], 99))
    ]
    assert drift == [], f"double-run drift on {len(drift)} gold items: {drift[:5]}"
    # sanity: the checker pair we ship is consistent with both rulers
    bad = [
        it["doc_id"]
        for it in items
        if not check_band_direction_consistency(
            {"attrs": {"expected_band": it["expected_band"],
                       "direction": _sign_to_direction(origin[it["expected_band"]])}}
        ).passed
    ]
    assert bad == [], f"shipped checker rejects origin-consistent units: {bad[:5]}"
