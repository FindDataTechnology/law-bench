#!/usr/bin/env python3
"""Dataset exporter: bronze guard, tier filtering, schema/rule validation, flywheel gate.

Reads warehouse material from ``data/finetune/warehouse/<table>.jsonl`` (produced
by ``extract_warehouse.py``) and builds the two training datasets:

- **Judge-C quadruples** — from ``eval_criteria_results`` (bronze, machine
  self-eval) and an optional human-annotation file (gold). Machine pass is
  forced to fail (spec scenario 机器自评不产生 pass).
- **Drafter-A pairs** — silver from two machine sources: ``pipeline_runs``
  (best-scoring run per duplicate body, quality metadata in provenance) and
  ``contract_artifacts`` master templates synthetically instantiated by the
  deterministic slot-value bank (``slot_value_bank.py``). Cross-source body
  dedup keeps the pipeline_runs draft on collision. An optional
  human-verified file (gold) is also merged. Slot consistency is checked
  with the CJK-aware placeholder regex.

Cross-field rules JSON Schema cannot express are enforced here:
- ``verdict=pass`` only when ``provenance.reviewer=human`` (machine → fail).
- ``reasoning.citation`` non-empty.
- bronze material never enters a ground-truth / reward-positive set
  (single-point guard in ``common.assert_not_ground_truth``).
- silver pairs never enter a reward-positive set (same guard, purpose=reward).

Subcommands::

    python scripts/finetune/export_dataset.py judge-c  [--gold PATH]
    python scripts/finetune/export_dataset.py drafter-a [--gold PATH]
    python scripts/finetune/export_dataset.py judge-c-scaffold
    python scripts/finetune/export_dataset.py validate {judge-c|drafter-a} --file PATH
    python scripts/finetune/export_dataset.py gate

``gate`` enforces the flywheel order: Drafter reward/DPO may only start when
the Judge-C gold quadruple dataset exists and is non-empty (spec: 飞轮顺序约束).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import slot_value_bank as svb  # noqa: E402
from common import (  # noqa: E402
    BronzeGroundTruthError,
    DRAFTER_A_DIR,
    JUDGE_C_DIR,
    SLOT_RE,
    WAREHOUSE_DIR,
    assert_not_ground_truth,
    filter_by_tier,
    read_jsonl,
    write_jsonl,
)

QUADRUPLE_SCHEMA = JUDGE_C_DIR / "quadruple.schema.json"
PAIR_SCHEMA = DRAFTER_A_DIR / "pair.schema.json"
JUDGE_C_GOLD = JUDGE_C_DIR / "judge_c_gold.jsonl"
JUDGE_C_BRONZE = JUDGE_C_DIR / "judge_c_bronze.jsonl"
DRAFTER_A_SILVER = DRAFTER_A_DIR / "drafter_a_silver.jsonl"
DRAFTER_A_GOLD = DRAFTER_A_DIR / "drafter_a_gold.jsonl"


# ---------------------------------------------------------------------------
# warehouse material loading
# ---------------------------------------------------------------------------

def _load_warehouse_table(table: str) -> list[dict]:
    """Load material records for one warehouse table (flat JSONL, not nested)."""
    return read_jsonl(WAREHOUSE_DIR / f"{table}.jsonl")


def _index_by_id(records: list[dict]) -> dict:
    """Index material records by their ``row_id``."""
    return {r["row_id"]: r for r in records}


def _index_criteria_by_name(records: list[dict]) -> dict:
    """Index criteria material by ``row.name``.

    ``eval_criteria_results.criterion_id`` is TEXT and holds the criterion
    *name* (e.g. 'party_identification'), not the criteria.id bigint. So the
    Judge-C join is on name, not id.
    """
    return {r["row"].get("name"): r for r in records}


# ---------------------------------------------------------------------------
# Judge-C quadruple construction
# ---------------------------------------------------------------------------

def _build_bronze_quadruples() -> list[dict]:
    """Build bronze quadruples from eval_criteria_results (machine self-eval).

    Machine verdict=pass is forced to fail (spec: 机器自评不产生 pass). The
    legal_base comes from the matching criterion's guidance (the human rule).
    """
    eval_results = _load_warehouse_table("eval_criteria_results")
    criteria_by_name = _index_criteria_by_name(_load_warehouse_table("criteria"))
    rubrics_by_id = _index_by_id(_load_warehouse_table("rubrics"))

    quadruples: list[dict] = []
    for er in eval_results:
        row = er["row"]
        # Join on criterion NAME (criterion_id is text, not a bigint id).
        crit = criteria_by_name.get(row.get("criterion_id"))
        if crit is None:
            continue
        crit_row = crit["row"]
        rubric = rubrics_by_id.get(crit_row.get("rubric_id"))
        rubric_context = rubric["row"].get("context", "") if rubric else ""

        machine_verdict = row.get("verdict", "fail")
        # Force machine pass → fail (spec scenario).
        verdict = "fail" if machine_verdict == "pass" else "fail"

        citation = []
        if rubric:
            citation.append(f"rubric:{rubric['row'].get('name')}")
        if crit_row.get("name"):
            citation.append(f"criterion:{crit_row.get('name')}")

        reasoning_text = row.get("reasoning") or crit_row.get("guidance") or ""
        if not reasoning_text:
            reasoning_text = "机器自评未提供理由；降级为 fail。"

        quadruples.append({
            "legal_base": {
                "source": f"rubric:{rubric['row'].get('name')}" if rubric else f"criterion:{crit_row.get('name')}",
                "text": (rubric_context + "\n" + crit_row.get("guidance", "")).strip() or crit_row.get("description", ""),
            },
            "clause_text": {
                "body": row.get("title") or crit_row.get("name") or "",
                "section": f"criterion:{row.get('criterion_id')}",
            },
            "verdict": verdict,
            "reasoning": {
                "justification": reasoning_text,
                "citation": citation or ["machine_self_eval:no_citation"],
            },
            "provenance": {
                "reviewer": "machine_self_eval",
                "annotated_by": "machine_self_eval",
                "id": f"eval_criteria_results:{row.get('id')}",
            },
            "tier": "bronze",
        })
    return quadruples


def _char_bigrams(text: str) -> set[str]:
    """Return adjacent-char bigrams (cheap language-agnostic relevance signal)."""
    text = (text or "").strip()
    return {text[i:i + 2] for i in range(len(text) - 1)} if len(text) >= 2 else set()


# Hard cap on candidate clauses per type_validation rule (design D5: ~500 total).
SCAFFOLD_TOP_K = 3
# Truncate law_info retrieval hints so a full LLM summary does not bloat records.
LAW_INFO_HINT_CHARS = 300


def _score_clause(rule_text: str, clause: dict) -> int:
    """Relevance score = char-bigram overlap between rule and (section + body)."""
    clause_text = (clause["row"].get("section") or "") + " " + (clause["row"].get("body") or "")
    return len(_char_bigrams(rule_text) & _char_bigrams(clause_text))


def _build_scaffold_quadruples() -> tuple[list[dict], int, int]:
    """Build candidate-quadruple scaffolds from type_validations x clauses x law_info.

    For each type_validation rule carrying a law_ref, select up to SCAFFOLD_TOP_K
    same-type clauses by char-bigram relevance (exact field==section match first,
    then keyword overlap; rules with zero overlap are skipped). law_info is a
    truncated retrieval hint, never authoritative text. Outputs tier=silver,
    verdict=fail (pending human verification), legal_base.source=law_info:<llm>.
    Returns (scaffolds, accepted_rule_count, skipped_rule_count).
    """
    type_vals = _load_warehouse_table("type_validations")
    clauses_by_type: dict[str, list[dict]] = {}
    for c in _load_warehouse_table("clauses"):
        ct = c["row"].get("contract_type")
        if ct:
            clauses_by_type.setdefault(ct, []).append(c)
    law_info_by_type: dict[str, list[dict]] = {}
    for li in _load_warehouse_table("law_info"):
        ct = li["row"].get("contract_type")
        if ct:
            law_info_by_type.setdefault(ct, []).append(li)

    scaffolds: list[dict] = []
    accepted_rules = 0
    skipped_rules = 0

    for tv in type_vals:
        row = tv["row"]
        law_ref = row.get("law_ref")
        if not law_ref:
            continue

        contract_type = row.get("contract_type")
        message = row.get("message") or ""
        constraint_id = row.get("constraint_id") or ""
        field = row.get("field")
        clause_rows = clauses_by_type.get(contract_type, [])
        if not clause_rows:
            skipped_rules += 1
            continue

        # Exact field==section match wins; otherwise rank by bigram overlap.
        rule_text = f"{constraint_id} {field or ''} {message}"
        scored: list[tuple[int, str, dict]] = []
        for cr in clause_rows:
            section = cr["row"].get("section") or ""
            body = cr["row"].get("body") or ""
            if not body:
                continue
            exact = bool(field) and (field == section)
            score = _score_clause(rule_text, cr)
            match_type = "exact" if exact else "fuzzy"
            if exact or score > 0:
                scored.append((10**9 if exact else score, match_type, cr))

        if not scored:
            skipped_rules += 1
            continue

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:SCAFFOLD_TOP_K]
        accepted_rules += 1

        law_rows = law_info_by_type.get(contract_type, [])
        law_sources = sorted({
            f"law_info:{lr['row'].get('source', 'unknown')}"
            for lr in law_rows if lr["row"].get("source")
        })
        law_hint = " ".join(
            (lr["row"].get("content") or "") for lr in law_rows
        )[:LAW_INFO_HINT_CHARS].strip()
        legal_base_source = law_sources[0] if law_sources else "law_info:unknown"
        legal_base_text = law_ref + (f"\n[retrieval hint] {law_hint}" if law_hint else "")

        for _score, match_type, cr in top:
            clause_body = cr["row"].get("body", "")
            scaffolds.append({
                "legal_base": {
                    "source": legal_base_source,
                    "text": legal_base_text,
                },
                "clause_text": {
                    "body": clause_body,
                    "section": f"clauses:{cr['row'].get('id')}",
                },
                "verdict": "fail",  # default: pending human verification
                "reasoning": {
                    "justification": message or "机器脚手架：待人工核验与修正",
                    "citation": [law_ref],
                },
                "provenance": {
                    "annotated_by": "machine_self_eval",
                    "reviewer": "machine_self_eval",
                    "id": (
                        f"scaffold:machine:type_validations:{row.get('id')}"
                        f":clause:{cr['row'].get('id')}:{match_type}"
                    ),
                },
                "tier": "silver",
            })

    return scaffolds, accepted_rules, skipped_rules


def _load_gold_quadruples(gold_path: pathlib.Path | None) -> list[dict]:
    """Load human-annotated gold quadruples from an optional file."""
    path = gold_path or JUDGE_C_GOLD
    return read_jsonl(path)


def export_judge_c(gold_path: pathlib.Path | None = None) -> dict:
    """Export Judge-C bronze + gold quadruple datasets."""
    bronze = _build_bronze_quadruples()
    write_jsonl(JUDGE_C_BRONZE, bronze)

    gold = _load_gold_quadruples(gold_path)
    if gold:
        write_jsonl(JUDGE_C_GOLD, gold)

    return {
        "bronze": len(bronze),
        "gold": len(gold),
        "bronze_path": str(JUDGE_C_BRONZE),
        "gold_path": str(JUDGE_C_GOLD),
    }


def export_judge_c_scaffold() -> dict:
    """Export Judge-C scaffold quadruples (machine-generated candidates for human review).

    Scaffolds are tier=silver, verdict=fail (pending verification), and routed
    through the bronze/silver guard so they cannot be used as ground truth.
    Human-verified outputs are promoted to gold via a separate annotation step.
    """
    scaffolds, accepted_rules, skipped_rules = _build_scaffold_quadruples()

    # Filter out non-schema-compliant scaffolds (spec: 脚手架过既有 JSON Schema 校验)
    valid_scaffolds: list[dict] = []
    rejected: list[str] = []

    for s in scaffolds:
        try:
            validate_quadruple(s, 0)  # minimal validation; full index done downstream
            valid_scaffolds.append(s)
        except ValidationError as e:
            rejected.append(str(e))

    JUDGE_C_SCAFFOLD = JUDGE_C_DIR / "judge_c_scaffold.jsonl"
    write_jsonl(JUDGE_C_SCAFFOLD, valid_scaffolds)

    print(
        f"  judge-c-scaffold: {len(valid_scaffolds)} candidates "
        f"from {accepted_rules} matched rules ({skipped_rules} rules skipped) "
        f"-> {JUDGE_C_SCAFFOLD}"
    )
    if rejected[:5]:
        print(f"    rejected: {rejected[:5]}")

    return {
        "scaffolds": len(valid_scaffolds),
        "accepted_rules": accepted_rules,
        "skipped_rules": skipped_rules,
        "rejected": len(rejected),
        "path": str(JUDGE_C_SCAFFOLD),
    }


# ---------------------------------------------------------------------------
# Drafter-A pair construction
# ---------------------------------------------------------------------------

def _fill_values_to_slots(fill_values) -> list[dict]:
    """Convert a pipeline_runs.fill_values jsonb dict to schema-compliant slots[]."""
    if not isinstance(fill_values, dict):
        return []
    return [{"name": str(k), "value": str(v) if v is not None else ""} for k, v in fill_values.items()]


def _check_slot_consistency(body: str, slots: list[dict]) -> tuple[bool, list[str]]:
    """Return (ok, leftover_placeholders). Body must have no unreplaced {{slot}}.

    Uses the CJK-aware shared regex (common.SLOT_RE): the old ASCII-only
    pattern silently passed {{甲方名称}} placeholders through as "filled".
    """
    leftover = SLOT_RE.findall(body or "")
    return (len(leftover) == 0, leftover)


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _run_quality(row: dict) -> tuple[float, int, str]:
    """Dedup sort key: score ratio desc, then all_pass, then later created_at."""
    score = row.get("score") or 0
    max_score = row.get("max_score") or 0
    ratio = round(score / max_score, 4) if max_score > 0 else 0.0
    return (ratio, 1 if row.get("all_pass") else 0, row.get("created_at") or "")


def _score_ratio(row: dict) -> float:
    score = row.get("score") or 0
    max_score = row.get("max_score") or 0
    return round(score / max_score, 2) if max_score > 0 else 0.0


def _build_silver_pairs() -> dict:
    """Build silver Drafter-A pairs from pipeline_runs.filled_text (LLM drafts).

    Groups rows by body hash; each duplicate group keeps its best run —
    score ratio desc, then all_pass, then the later created_at — whose row
    still passes the slot-consistency and task_desc checks. The retained
    pair's provenance carries ``score_ratio`` and ``all_pass`` so the trainer
    can down-weight weak drafts (in the 2026-08 snapshot only 2/150 distinct
    bodies reach ratio >= 0.8, so the metadata is load-bearing).
    """
    runs = _load_warehouse_table("pipeline_runs")
    groups: dict[str, list[dict]] = {}
    pre_count = 0
    for run in runs:
        row = run["row"]
        body = row.get("filled_text")
        if not body:
            continue
        pre_count += 1
        groups.setdefault(_body_hash(body), []).append(row)

    pairs: list[dict] = []
    invalid_groups = 0
    for group in groups.values():
        group.sort(key=_run_quality, reverse=True)
        chosen = None
        for row in group:
            ok, _leftover = _check_slot_consistency(row["filled_text"], None)
            if ok and (row.get("task_desc") or ""):
                chosen = row
                break
        if chosen is None:
            invalid_groups += 1
            continue
        pairs.append({
            "task_desc": chosen["task_desc"],
            "slots": _fill_values_to_slots(chosen.get("fill_values")),
            "body": chosen["filled_text"],
            "provenance": {
                "annotated_by": "machine_generated",
                "id": f"pipeline_runs:{chosen.get('id')}",
                # Carried so the pool stays filterable by type/scenario/stance.
                # Coverage is lopsided (stance=balanced dominates) and that
                # skew is invisible once these are dropped.
                "contract_type": chosen.get("contract_type"),
                "scenario": (chosen.get("tags") or {}).get("scenario"),
                "stance": (chosen.get("tags") or {}).get("stance") or chosen.get("stance"),
                # Quality metadata for downstream down-weighting (design D4).
                "score_ratio": _score_ratio(chosen),
                "all_pass": bool(chosen.get("all_pass")),
            },
            "tier": "silver",
        })

    return {
        "pairs": pairs,
        "pre_count": pre_count,
        "distinct": len(groups),
        "valid": len(pairs),
        "invalid_groups": invalid_groups,
    }


def _build_synth_pairs() -> dict:
    """Build silver pairs from contract_artifacts master templates.

    Synthetic slot instantiation (design D1/D2): skips superseded rows, drops
    rows whose placeholders are not covered by the row's ``slots`` list
    (structural mismatch — never partially filled), and fills every
    ``{{槽位名}}`` with deterministic bank values. Unclassifiable long-tail
    names draw generic legal fillers; usage is counted for audit. task_desc
    is synthesized from the type zh-name, scenario, and stance.
    """
    rows = _load_warehouse_table("contract_artifacts")
    pairs: list[dict] = []
    skipped_superseded = 0
    skipped_empty = 0
    dropped_mismatch = 0
    fallback_rows = 0
    fallback_names: Counter = Counter()

    for rec in rows:
        row = rec["row"]
        if row.get("superseded_at"):
            skipped_superseded += 1
            continue
        body = row.get("body_text")
        if not body:
            skipped_empty += 1
            continue
        declared = set(row.get("slots") or [])
        placeholders = set(SLOT_RE.findall(body))
        if placeholders - declared:
            dropped_mismatch += 1
            continue

        filled, values, fallback = svb.instantiate(body)
        if SLOT_RE.search(filled):  # safety net; instantiate() guarantees this
            dropped_mismatch += 1
            continue

        pairs.append({
            "task_desc": svb.synth_task_desc(
                row.get("contract_type"), row.get("scenario"), row.get("stance")),
            "slots": [{"name": n, "value": values[n]} for n in sorted(values)],
            "body": filled,
            "provenance": {
                "annotated_by": "machine_generated",
                "id": f"contract_artifacts:{row.get('id')}",
                "contract_type": row.get("contract_type"),
                "scenario": row.get("scenario"),
                "stance": row.get("stance"),
                "synthetic_slots": True,
            },
            "tier": "silver",
        })
        if fallback:
            fallback_rows += 1
            fallback_names.update(fallback)

    return {
        "pairs": pairs,
        "rows_total": len(rows),
        "skipped_superseded": skipped_superseded,
        "skipped_empty": skipped_empty,
        "dropped_mismatch": dropped_mismatch,
        "fallback_rows": fallback_rows,
        "fallback_names": dict(fallback_names),
    }


def _load_gold_pairs(gold_path: pathlib.Path | None) -> list[dict]:
    path = gold_path or DRAFTER_A_GOLD
    return read_jsonl(path)


def export_drafter_a(gold_path: pathlib.Path | None = None) -> dict:
    """Export Drafter-A silver + gold pair datasets (dual-source, spec delta)."""
    pipe = _build_silver_pairs()
    synth = _build_synth_pairs()

    # Cross-source dedup: pipeline drafts enter first and win collisions
    # (spec: 跨源碰撞保留草稿源).
    seen = {_body_hash(p["body"]) for p in pipe["pairs"]}
    synth_pairs: list[dict] = []
    cross_dropped = 0
    for p in synth["pairs"]:
        h = _body_hash(p["body"])
        if h in seen:
            cross_dropped += 1
            continue
        seen.add(h)
        synth_pairs.append(p)

    silver = pipe["pairs"] + synth_pairs
    write_jsonl(DRAFTER_A_SILVER, silver)

    gold = _load_gold_pairs(gold_path)
    if gold:
        write_jsonl(DRAFTER_A_GOLD, gold)

    print(
        f"  银牌池：pipeline_runs 去重前 {pipe['pre_count']} / distinct "
        f"{pipe['distinct']} / 有效 {pipe['valid']}（无效组 {pipe['invalid_groups']}）"
    )
    print(
        f"           contract_artifacts {synth['rows_total']} 行"
        f"（superseded {synth['skipped_superseded']}，错配丢弃 {synth['dropped_mismatch']}）"
        f" → 实例化 {len(synth['pairs'])} 条"
    )
    print(
        f"           跨源碰撞丢弃 {cross_dropped}；兜底值行 {synth['fallback_rows']}"
        f"（{len(synth['fallback_names'])} 个长尾槽位名）"
    )
    print(f"           合计 silver {len(silver)} 条")

    return {
        "silver": len(silver),
        "gold": len(gold),
        "pipeline": {k: pipe[k] for k in
                     ("pre_count", "distinct", "valid", "invalid_groups")},
        "artifacts": {k: synth[k] for k in
                      ("rows_total", "skipped_superseded", "skipped_empty",
                       "dropped_mismatch", "fallback_rows")},
        "cross_source_dropped": cross_dropped,
        "silver_path": str(DRAFTER_A_SILVER),
        "gold_path": str(DRAFTER_A_GOLD),
    }


# ---------------------------------------------------------------------------
# validation (schema + cross-field rules)
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    pass


def _require(obj: dict, field: str, ctx: str) -> None:
    if field not in obj or obj[field] is None:
        raise ValidationError(f"{ctx}: 缺少必填字段 {field!r}")


def validate_quadruple(q: dict, index: int) -> None:
    """Validate one Judge-C quadruple against schema + annotation rules."""
    ctx = f"quadruple#{index}"
    _require(q, "legal_base", ctx)
    _require(q, "clause_text", ctx)
    _require(q, "verdict", ctx)
    _require(q, "reasoning", ctx)
    _require(q, "provenance", ctx)
    _require(q, "tier", ctx)

    lb = q["legal_base"]
    _require(lb, "source", ctx)
    _require(lb, "text", ctx)
    if not lb["source"] or not lb["text"]:
        raise ValidationError(f"{ctx}: 推理理由缺少法律依据 (legal_base 空)")

    ct = q["clause_text"]
    _require(ct, "body", ctx)
    if not ct["body"]:
        raise ValidationError(f"{ctx}: clause_text.body 为空")

    if q["verdict"] not in ("pass", "fail"):
        raise ValidationError(f"{ctx}: verdict 非 pass/fail")

    rs = q["reasoning"]
    _require(rs, "justification", ctx)
    _require(rs, "citation", ctx)
    if not rs["citation"]:
        raise ValidationError(f"{ctx}: 推理理由缺少法律依据 (citation 空)")

    prov = q["provenance"]
    _require(prov, "reviewer", ctx)
    _require(prov, "annotated_by", ctx)
    # Accept human, machine_self_eval, and ai_reviewer (AI-verified gold).
    if prov["reviewer"] not in ("human", "machine_self_eval", "ai_reviewer"):
        raise ValidationError(f"{ctx}: reviewer 非 human/machine_self_eval/ai_reviewer")

    # Cross-field rules: tier=gold requires either human or ai_reviewer (not self-eval).
    if q["tier"] == "gold" and prov["reviewer"] not in ("human", "ai_reviewer"):
        raise ValidationError(f"{ctx}: tier=gold 须 reviewer=human/ai_reviewer")
    # verdict=pass allowed for human or ai_reviewer; scaffold silver must be fail.
    if q["verdict"] == "pass" and prov["reviewer"] not in ("human", "ai_reviewer"):
        raise ValidationError(
            f"{ctx}: verdict=pass 须 reviewer=human/ai_reviewer (机器自评不得判 pass)"
        )
    # tier=silver is scaffold only: machine-generated, verdict must be fail.
    if q["tier"] == "silver":
        if prov["reviewer"] != "machine_self_eval":
            raise ValidationError(f"{ctx}: tier=silver (脚手架) 须 reviewer=machine_self_eval")
        if q["verdict"] != "fail":
            raise ValidationError(f"{ctx}: tier=silver (脚手架) verdict 须为 fail")
    # NOTE: the bronze "never ground truth" guard is NOT invoked here —
    # validating a bronze record is not the same as *using* it as ground
    # truth. The guard lives in common.filter_by_tier / assert_not_ground_truth
    # and is tripped by loaders that assemble ground-truth sets.


def validate_pair(p: dict, index: int) -> None:
    """Validate one Drafter-A pair against schema + slot-consistency rule."""
    ctx = f"pair#{index}"
    _require(p, "task_desc", ctx)
    _require(p, "slots", ctx)
    _require(p, "body", ctx)
    _require(p, "provenance", ctx)
    _require(p, "tier", ctx)

    if not p["task_desc"]:
        raise ValidationError(f"{ctx}: task_desc 为空")
    if not isinstance(p["slots"], list):
        raise ValidationError(f"{ctx}: slots 非数组")
    # minItems:0 — zero-slot pairs are valid iff body has no placeholders.
    for s in p["slots"]:
        _require(s, "name", ctx)
        _require(s, "value", ctx)
    if not p["body"]:
        raise ValidationError(f"{ctx}: body 为空")

    ok, leftover = _check_slot_consistency(p["body"], p["slots"])
    if not ok:
        raise ValidationError(f"{ctx}: 正文含未替换占位符 {leftover}")

    prov = p["provenance"]
    _require(prov, "annotated_by", ctx)
    if p["tier"] not in ("gold", "silver"):
        raise ValidationError(f"{ctx}: tier 非 gold/silver")
    if p["tier"] == "gold" and prov.get("annotated_by") != "human":
        raise ValidationError(f"{ctx}: tier=gold 须 annotated_by=human")
    # NOTE: the silver "never reward positive" guard is NOT invoked here —
    # validating a silver pair is not *using* it as a reward sample. The
    # guard lives in common.filter_by_tier / assert_not_ground_truth.


def validate_file(path: pathlib.Path, kind: str) -> int:
    """Validate every record in a dataset file. Returns count of valid records."""
    records = read_jsonl(path)
    validator = validate_quadruple if kind == "judge-c" else validate_pair
    valid = 0
    errors: list[str] = []
    for i, rec in enumerate(records):
        try:
            validator(rec, i)
            valid += 1
        except (ValidationError, BronzeGroundTruthError) as e:
            errors.append(str(e))
    print(f"  {path}: {valid}/{len(records)} valid")
    for e in errors[:10]:
        print(f"    - {e}")
    if len(errors) > 10:
        print(f"    ... ({len(errors) - 10} more)")
    return valid


# ---------------------------------------------------------------------------
# flywheel order gate (D4)
# ---------------------------------------------------------------------------

def flywheel_gate() -> bool:
    """Return True if a Judge-C gold quadruple dataset exists and is non-empty.

    Prefers the regrounded set. The raw ``judge_c_gold.jsonl`` has
    ``clause_text.body`` lifted from ``reasoning.justification`` in 96% of rows
    (see ``reground_judge_c.py``), so opening the gate on it alone would
    authorize Drafter reward/DPO on a judge signal that cannot generalize —
    hence the warning rather than a silent pass.
    """
    grounded = JUDGE_C_DIR / "judge_c_gold.grounded.jsonl"
    path = grounded if grounded.exists() else JUDGE_C_GOLD
    if not path.exists():
        print(f"❌ 飞轮闸门未通过: Judge-C gold 数据集不存在 ({path})")
        print("   先运行: python scripts/finetune/export_dataset.py judge-c --gold <human_gold.jsonl>")
        return False
    records = read_jsonl(path)
    if not records:
        print(f"❌ 飞轮闸门未通过: Judge-C gold 数据集为空 ({path})")
        return False
    print(f"✅ 飞轮闸门通过: Judge-C gold 有 {len(records)} 条四元组 ({path.name})")
    if path is not grounded:
        print("   ⚠️  用的是未重接地的 judge_c_gold.jsonl —— 96% 的 clause_text.body "
              "抄自 reasoning.justification（输入含答案）。")
        print("      先跑: python scripts/finetune/reground_judge_c.py build")
    return True


# ---------------------------------------------------------------------------
# reward-positive loader (§6.4 / §7.2 — silver must never be a reward positive)
# ---------------------------------------------------------------------------

def load_drafter_reward_positive() -> list[dict]:
    """Load Drafter-A pairs eligible as reward-positive samples.

    Gold only. Silver pairs are SFT-warmup-only and MUST NOT enter this set
    (spec §6.4, design D2). The silver exclusion is enforced two ways:
    (1) ``filter_by_tier(floor='gold')`` drops silver by rank, and
    (2) ``assert_not_ground_truth('silver', purpose='reward_positive')`` is
    an explicit trip-wire on any silver record that slipped past the filter.
    """
    pairs = read_jsonl(DRAFTER_A_GOLD) + read_jsonl(DRAFTER_A_SILVER)
    gold = filter_by_tier(pairs, "gold")
    # Belt-and-suspenders: if any silver record reached the gold set, fail loud.
    for p in gold:
        if p.get("tier") == "silver":
            assert_not_ground_truth("silver", purpose="drafter_a_reward_positive")
    return gold


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export & validate finetune datasets.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_jc = sub.add_parser("judge-c", help="export Judge-C quadruples")
    p_jc.add_argument("--gold", type=pathlib.Path, help="human gold quadruple file")

    p_da = sub.add_parser("drafter-a", help="export Drafter-A pairs")
    p_da.add_argument("--gold", type=pathlib.Path, help="human gold pair file")

    sub.add_parser("judge-c-scaffold", help="build Judge-C candidate scaffolds (type_validations × clauses × law_info)")

    p_val = sub.add_parser("validate", help="validate a dataset file")
    p_val.add_argument("kind", choices=["judge-c", "drafter-a"])
    p_val.add_argument("--file", type=pathlib.Path, required=True)

    sub.add_parser("gate", help="check flywheel order gate (Judge-C gold ready?)")

    args = parser.parse_args(argv)

    if args.cmd == "judge-c":
        stats = export_judge_c(getattr(args, "gold", None))
        print(f"Judge-C: bronze={stats['bronze']} -> {stats['bronze_path']}")
        print(f"         gold={stats['gold']} -> {stats['gold_path']}")
        return 0

    if args.cmd == "drafter-a":
        stats = export_drafter_a(getattr(args, "gold", None))
        print(f"Drafter-A: silver={stats['silver']} -> {stats['silver_path']}")
        print(f"           gold={stats['gold']} -> {stats['gold_path']}")
        return 0

    if args.cmd == "judge-c-scaffold":
        stats = export_judge_c_scaffold()
        print(f"Judge-C scaffold: scaffolds={stats['scaffolds']} matched_rules={stats['accepted_rules']} skipped={stats['skipped_rules']} rejected={stats['rejected']} -> {stats['path']}")
        return 0

    if args.cmd == "validate":
        n = validate_file(args.file, args.kind)
        return 0 if n > 0 else 1

    if args.cmd == "gate":
        return 0 if flywheel_gate() else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
