#!/usr/bin/env python3
"""Verification suite for expand-finetune-data-sources (§2, §3.4, §5, §6)."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import (  # noqa: E402
    filter_by_tier,
    assert_not_ground_truth,
    TierGuardError,
    write_jsonl,
    read_jsonl,
)
from export_dataset import (  # noqa: E402
    _load_warehouse_table,
    load_drafter_reward_positive,
    flywheel_gate,
    JUDGE_C_GOLD,
)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}: {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# §2.1 new-table provenance/source/tier
for t in ["type_validations", "core_clauses", "industry_standard_references"]:
    rows = _load_warehouse_table(t)
    ok = bool(rows) and all(
        r["source"] == "warehouse"
        and r["provenance"] == f"{t}:{r['row_id']}"
        and r["tier"] == "gold"
        for r in rows
    )
    check(f"§2.1 {t}: provenance/source:warehouse/tier=gold ({len(rows)} rows)", ok)

# §2.2 law_info(bronze) excluded from ground-truth floor + guard trips
li = _load_warehouse_table("law_info")
gold_floor = filter_by_tier(li, "gold")
check("§2.2 law_info excluded from filter_by_tier(floor=gold)", len(gold_floor) == 0, f"leaked={len(gold_floor)}")
guard_tripped = False
try:
    assert_not_ground_truth("bronze", purpose="ground_truth")
except TierGuardError:
    guard_tripped = True
check("§2.2 assert_not_ground_truth(bronze) trips", guard_tripped)

# §2.3 contract_artifacts(raw) not in gold/silver output
ca = _load_warehouse_table("contract_artifacts")
all_raw = all(r["tier"] == "raw" for r in ca)
silver_floor = filter_by_tier(ca, "silver")
check(f"§2.3 contract_artifacts all raw ({len(ca)} rows), none in gold/silver", all_raw and len(silver_floor) == 0)

# §3.4 silver excluded from reward-positive
rp = load_drafter_reward_positive()
rp_gold_only = all(p["tier"] == "gold" for p in rp)
check(f"§3.4 reward-positive set gold-only ({len(rp)} records, silver excluded)", rp_gold_only)

# §6.1 scaffold legal_base.source tagged law_info:<llm>, tier=silver
scaffolds = read_jsonl(pathlib.Path("data/finetune/judge-c/judge_c_scaffold.jsonl"))
silver_count = sum(1 for s in scaffolds if s["tier"] == "silver")
src_tagged = sum(1 for s in scaffolds if s["legal_base"]["source"].startswith("law_info:"))
check(
    f"§6.1 scaffolds tier=silver & source law_info:* ({silver_count}/{len(scaffolds)} silver, {src_tagged} tagged)",
    silver_count == len(scaffolds) and src_tagged == len(scaffolds),
)

# §4.4/§5.1/§5.2/§5.3 gate tests need an empty-gold starting state, and they
# write + unlink JUDGE_C_GOLD. Both real gold files are moved aside first and
# restored in the `finally` below — without this the run silently destroys the
# 1074/1969-row gold sets and reports a false §4.4 failure.
_GROUNDED = JUDGE_C_GOLD.parent / "judge_c_gold.grounded.jsonl"
_stashed: list[tuple[pathlib.Path, pathlib.Path]] = []
for _p in (JUDGE_C_GOLD, _GROUNDED):
    if _p.exists():
        _bak = _p.with_suffix(_p.suffix + ".verify-bak")
        _p.replace(_bak)
        _stashed.append((_p, _bak))

try:
    # §4.4 builder never writes judge_c_gold.jsonl
    check("§4.4 builder did not create judge_c_gold.jsonl", not JUDGE_C_GOLD.exists())

    # §5.3 flywheel_gate closed when gold empty
    gate_closed_before = not flywheel_gate()
    check("§5.3 flywheel_gate closed (gold empty)", gate_closed_before)

    # §5.1/§5.2 promotion path: a synthetic human gold record opens the gate, then cleanup
    synthetic = [{
        "legal_base": {"source": "民法典§509", "text": "当事人应当按照约定全面履行自己的义务。"},
        "clause_text": {"body": "甲方应按约交付标的物。", "section": "clauses:1"},
        "verdict": "pass",
        "reasoning": {"justification": "条款符合全面履行原则", "citation": ["民法典§509"]},
        "provenance": {"annotated_by": "human_annotated", "reviewer": "human", "id": "test:synthetic:1"},
        "tier": "gold",
    }]
    write_jsonl(JUDGE_C_GOLD, synthetic)
    gate_opens_after = flywheel_gate()
    check("§5.3 flywheel_gate opens when judge_c_gold non-empty", gate_opens_after)
    # cleanup synthetic gold
    JUDGE_C_GOLD.unlink()
    gate_closed_after_cleanup = not flywheel_gate()
    check("§5.3 gate re-closes after synthetic gold removed", gate_closed_after_cleanup)
finally:
    for _p, _bak in _stashed:
        if JUDGE_C_GOLD.exists() and _p == JUDGE_C_GOLD:
            JUDGE_C_GOLD.unlink()
        _bak.replace(_p)

print()
if failures:
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALL CHECKS PASSED")
