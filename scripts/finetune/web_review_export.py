#!/usr/bin/env python3
"""Agreement statistics + gold export for web human review (add-web-human-review).

Reads decided ``review_tasks`` rows, reports:

- per-annotator decision counts,
- annotator-pair agreement and Cohen's kappa on double-annotated items,
- human-vs-judge agreement (per annotator and overall),

and flags any annotator whose agreement with the judge is at or above
``--judge-agreement-warn`` — a person agreeing with the model on *everything* is
the signature of machine-mediated (or copy-pasted) labelling, and the flywheel's
whole premise is that machine self-eval never becomes ground truth.

Then it exports ``approved`` gold-curation tasks as judge-C quadruples in the
canonical nested shape (``clause_text.body`` / ``legal_base`` / ``reasoning`` /
``provenance``) that ``export_dataset.validate_quadruple`` accepts, stamped with
reviewer provenance. Every record passes that same validator before it reaches
the gold file; the rest land in ``<out>.incomplete.jsonl`` as a hand-completion
worklist (the eval-side tables carry no law reference, so ``legal_base`` and
``reasoning.citation`` are empty rather than invented).

    python scripts/finetune/web_review_export.py --batch-id v4-validity-pilot
    python scripts/finetune/web_review_export.py --batch-id v4-gold --export
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.eval.db import connect  # noqa: E402
from src.eval.store import ensure_schema  # noqa: E402
from export_dataset import ValidationError, validate_quadruple  # noqa: E402

DEFAULT_OUT = Path("data/finetune/judge-c/judge_c_gold.web.jsonl")

_DECIDED_SQL = """
SELECT t.id AS task_id, t.batch_id, t.batch_type, t.slot, t.annotator,
       t.annotator_verdict, t.note, t.reviewed_at,
       r.id AS result_id, r.criterion_id, r.title AS criterion_title,
       r.verdict AS model_verdict, r.reasoning AS model_reasoning,
       e.id AS run_id, e.rubric_name, e.draft_text, e.judge_model, e.scored_at
FROM review_tasks t
JOIN eval_criteria_results r ON r.id = t.eval_criteria_result_id
JOIN eval_runs e ON e.id = r.run_id
WHERE t.status = 'decided' {batch_clause}
ORDER BY t.batch_id, r.id, t.slot
"""


def _normalized_label(row: dict) -> str | None:
    """Human verdict mapped onto the judge's pass/fail axis.

    ``validity`` rows carry the annotator's own verdict; ``gold_curation`` rows
    carry an endorsement, which maps onto the model verdict it endorses.
    ``skipped`` carries no label.
    """
    if row["batch_type"] == "validity":
        return row["annotator_verdict"] if row["annotator_verdict"] in ("pass", "fail") else None
    mapping = {"approved": "pass", "rejected": "fail"}
    return mapping.get(row["annotator_verdict"] or "")


def _agrees(row: dict) -> bool | None:
    label = _normalized_label(row)
    if label is None or row["model_verdict"] not in ("pass", "fail"):
        return None
    return label == row["model_verdict"]


def cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for two raters over binary labels; None when undefined."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    a_pass = sum(1 for a, _ in pairs if a == "pass") / n
    b_pass = sum(1 for _, b in pairs if b == "pass") / n
    pe = a_pass * b_pass + (1 - a_pass) * (1 - b_pass)
    if pe >= 1.0:  # degenerate: both raters constant -> kappa undefined
        return None
    return (po - pe) / (1 - pe)


def _load(batch_id: str | None) -> list[dict]:
    ensure_schema()
    conn = connect()
    try:
        sql = _DECIDED_SQL.format(
            batch_clause="AND t.batch_id = %s" if batch_id else ""
        )
        params = (batch_id,) if batch_id else ()
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _report(rows: list[dict], warn_threshold: float) -> dict:
    per_annotator: dict[str, dict] = defaultdict(lambda: {"decided": 0, "agree": 0, "judged": 0})
    by_item: dict[tuple[str, int], dict[str, str]] = defaultdict(dict)

    for row in rows:
        who = row["annotator"] or "(unknown)"
        stats = per_annotator[who]
        stats["decided"] += 1
        label = _normalized_label(row)
        agree = _agrees(row)
        if agree is not None:
            stats["judged"] += 1
            stats["agree"] += int(agree)
        if label is not None:
            by_item[(row["batch_id"], row["result_id"])][who] = label

    print(f"decided tasks: {len(rows)}")
    print("\nper annotator:")
    flagged = []
    for who in sorted(per_annotator):
        s = per_annotator[who]
        rate = (s["agree"] / s["judged"]) if s["judged"] else None
        shown = f"{rate:.3f}" if rate is not None else "n/a"
        print(f"  {who:<32} decided={s['decided']:<4} vs judge={shown} (n={s['judged']})")
        if rate is not None and rate >= warn_threshold and s["judged"] >= 5:
            flagged.append((who, rate))
            print(f"      ⚠ 与判官一致率 {rate:.3f} ≥ {warn_threshold} — 疑似机器代打，请人工核实")

    pairs: list[tuple[str, str]] = []
    for key, labels in sorted(by_item.items()):
        names = sorted(labels)
        if len(names) < 2:
            continue
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pairs.append((labels[names[i]], labels[names[j]]))
    if pairs:
        agree_rate = sum(1 for a, b in pairs if a == b) / len(pairs)
        kappa = cohens_kappa(pairs)
        print(f"\nannotator-pair agreement on double-annotated items: "
              f"{agree_rate:.3f} (n={len(pairs)})")
        print(f"Cohen's kappa: {kappa:.3f}" if kappa is not None else "Cohen's kappa: undefined (degenerate marginals)")
    else:
        print("\nno double-annotated items — kappa not computable")

    judged = [r for r in rows if _agrees(r) is not None]
    if judged:
        overall = sum(1 for r in judged if _agrees(r)) / len(judged)
        print(f"human-vs-judge agreement overall: {overall:.3f} (n={len(judged)})")

    return {"flagged": flagged, "pairs": len(pairs)}


def _record(row: dict) -> dict:
    """One approved gold-curation task as a canonical judge-C quadruple.

    The legal basis is taken from the row when the joined data carries one
    (``legal_base_source`` / ``legal_base_text`` / ``citation``) and left empty
    otherwise — ``criteria`` holds only name/description/guidance, so today it
    always comes out empty, and it is counted rather than invented from
    ``law_info`` (a retrieval hint is not a citation; the scaffold path rejects
    exactly that).
    """
    return {
        "clause_text": {"body": row["draft_text"] or ""},
        "legal_base": {
            "source": row.get("legal_base_source") or "",
            "text": row.get("legal_base_text") or "",
        },
        "reasoning": {
            "justification": row["model_reasoning"] or "",
            "citation": row.get("citation") or "",
        },
        "verdict": row["model_verdict"],
        "tier": "gold",
        "provenance": {
            "reviewer": "human",
            "annotated_by": row["annotator"],
            "source": (
                f"review_tasks:{row['task_id']}"
                f"|eval_criteria_results:{row['result_id']}"
                f"|eval_runs:{row['run_id']}"
            ),
            "review": {
                "batch_id": row["batch_id"],
                "slot": row["slot"],
                "status": "approved",
                "reviewed_at": str(row["reviewed_at"]),
                "note": row["note"],
            },
        },
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _export(rows: list[dict], out_path: Path) -> None:
    """Split approved gold-curation tasks into promotable and incomplete gold.

    ``validate_quadruple`` is the same gate ``promote`` / ``gate`` apply
    downstream, so running it here means the gold file never contains a record
    the flywheel would reject — an empty-but-written gold file would falsely
    unblock the Drafter stage. The gold file is therefore only written when it
    has at least one passing record; failures become a worklist for a human.
    """
    complete: list[dict] = []
    incomplete: list[dict] = []
    for row in rows:
        if row["batch_type"] != "gold_curation" or row["annotator_verdict"] != "approved":
            continue
        record = _record(row)
        try:
            validate_quadruple(record, len(complete) + len(incomplete))
        except ValidationError as exc:
            record["_validation_error"] = str(exc)
            incomplete.append(record)
        else:
            complete.append(record)

    if complete:
        _write_jsonl(out_path, complete)
        print(f"\nexported {len(complete)} promotable quadruple(s) -> {out_path}")
    elif incomplete:
        print(f"\nno promotable quadruple — gold file left untouched ({out_path})")

    if incomplete:
        incomplete_path = out_path.with_suffix(out_path.suffix + ".incomplete.jsonl")
        _write_jsonl(incomplete_path, incomplete)
        print(f"{len(incomplete)} approved record(s) need a legal basis -> {incomplete_path}")
        for reason in sorted({r["_validation_error"] for r in incomplete}):
            print(f"  ✗ {reason}")
        print("  补齐 legal_base.source/text 与 reasoning.citation 后再晋金；"
              "不补则不得作 ground truth")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch-id", help="limit to one batch (default: every batch)")
    ap.add_argument("--judge-agreement-warn", type=float, default=0.98,
                    help="flag annotators at/above this agreement with the judge (default 0.98)")
    ap.add_argument("--export", action="store_true", help="write the gold JSONL")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = _load(args.batch_id)
    if not rows:
        print("no decided review tasks — nothing to report")
        return
    _report(rows, args.judge_agreement_warn)
    if args.export:
        _export(rows, args.out)


if __name__ == "__main__":
    main()
