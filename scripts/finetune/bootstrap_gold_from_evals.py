#!/usr/bin/env python3
"""Bootstrap Judge-C gold seeds from existing eval history.

Joins ``eval_criteria_results`` (9134 model judgments with reasoning) with
``criteria`` (231 human-authored rules with PASS/FAIL guidance) and
``eval_runs`` (run metadata). Each result becomes a review envelope in the
same shape as ``prepare_review_batches.prepare`` so the human can use the
same y/n/s CLI to approve.

Output: per-rubric batches in ``data/finetune/review/inbox/bootstrap/``,
each with a confidence score (0-1) so the interactive CLI can sort and
prioritize the easiest ones first.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import (  # noqa: E402
    FINETUNE_ROOT,
    read_jsonl,
    write_jsonl,
)

REVIEW_DIR = FINETUNE_ROOT / "review"
INBOX_DIR = REVIEW_DIR / "inbox"
BOOTSTRAP_DIR = INBOX_DIR / "bootstrap"
WAREHOUSE = FINETUNE_ROOT / "warehouse"

# Heuristics: each contributing 0..1 of confidence.
CHINESE_RE = re.compile(r"[一-鿿]")
ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百零〇\d]+条|§\s*\d+|Article\s+\d+")
SPECIFIC_QUOTE_RE = re.compile(r"[\"“]([^\"”]{15,200})[\"”]|「([^」]{15,200})」")


def _confidence(reasoning: str, verdict: str, judge_model: str | None) -> float:
    """0..1 score: high when reasoning is detailed, has specific references,
    and was produced by a known good judge model. Used to sort envelopes
    so the human sees the easiest approvals first.
    """
    if not reasoning:
        return 0.0
    score = 0.0
    # length: 100 chars is the "thoughtful" threshold
    score += min(len(reasoning) / 300.0, 0.4)
    # specific reference (article / section)
    if ARTICLE_RE.search(reasoning):
        score += 0.2
    # quoted fragment
    if SPECIFIC_QUOTE_RE.search(reasoning):
        score += 0.15
    # Chinese content: more likely to be the original language
    if CHINESE_RE.search(reasoning):
        score += 0.1
    # known judge models
    if judge_model in ("kmodel_latest", "glm-5.2", "kimi-k3"):
        score += 0.15
    elif judge_model:
        score += 0.05
    # pass verdicts are slightly easier to confirm (less subjective)
    if verdict == "pass":
        score += 0.05
    return min(score, 1.0)


def _extract_clause_text(reasoning: str, run_id: int, crit_name: str) -> dict:
    """Best-effort clause_text from the reasoning."""
    # try quoted fragments first
    m = SPECIFIC_QUOTE_RE.search(reasoning)
    if m:
        quote = next(g for g in m.groups() if g)
        return {"body": quote, "section": f"eval_runs:{run_id}:criterion:{crit_name}"}
    # fallback: first 200 chars of reasoning
    return {"body": reasoning[:200], "section": f"eval_runs:{run_id}:criterion:{crit_name}"}


def cmd_build(_args: argparse.Namespace) -> int:
    results = read_jsonl(WAREHOUSE / "eval_criteria_results.jsonl")
    criteria = {c["row"]["name"]: c["row"] for c in read_jsonl(WAREHOUSE / "criteria.jsonl")}
    runs = {r["row"]["id"]: r["row"] for r in read_jsonl(WAREHOUSE / "eval_runs.jsonl")}
    rubrics = {r["row"]["id"]: r["row"] for r in read_jsonl(WAREHOUSE / "rubrics.jsonl")}

    print(f"results={len(results)} criteria_matched={len(criteria)} runs={len(runs)}")

    envelopes: list[dict] = []
    skipped = 0
    for rec in results:
        r = rec["row"]
        crit = criteria.get(r.get("criterion_id"))
        run = runs.get(r.get("run_id"))
        if not crit or not run:
            skipped += 1
            continue

        rubric = rubrics.get(crit.get("rubric_id"), {})
        crit_name = crit["name"]
        rubric_name = rubric.get("name", crit.get("rubric_id"))
        reasoning = (r.get("reasoning") or "").strip()
        verdict = r.get("verdict", "fail")
        judge_model = run.get("judge_model")
        conf = _confidence(reasoning, verdict, judge_model)

        envelope = {
            "scaffold_id": f"bootstrap:run:{r['run_id']}:crit:{crit_name}",
            "contract_type": "bootstrap",  # these cover any contract type via the rubric
            "rule": {
                "id": crit.get("id"),
                "constraint_id": crit_name,
                "field": None,
                "severity": None,
                "message": crit.get("description", ""),
                "law_ref": None,
            },
            "match": "bootstrap",
            "clause_id": r["run_id"],
            "rubric": {"id": crit.get("rubric_id"), "name": rubric_name},
            "judge_model": judge_model,
            "contract_path": run.get("contract_path"),
            "run_summary": run.get("summary"),
            "confidence": round(conf, 3),
            "quadruple": {
                "legal_base": {
                    "source": f"criteria:{crit_name} (rubric:{rubric_name})",
                    "text": crit["guidance"],
                },
                "clause_text": _extract_clause_text(reasoning, r["run_id"], crit_name),
                "verdict": verdict,
                "reasoning": {
                    "justification": reasoning,
                    "citation": [crit_name],
                },
                "provenance": {
                    "id": f"seed:bootstrap:run:{r['run_id']}:crit:{crit_name}",
                    "reviewer": "machine_self_eval",
                    "annotated_by": "ai_reviewed",
                    "judge_model": judge_model,
                    "contract_path": run.get("contract_path"),
                },
                "tier": "silver",
            },
            "review": {
                "status": "ai_seeded",
                "annotator": None,
                "notes": "",
                "confidence": conf,
            },
        }
        envelopes.append(envelope)

    # Group by rubric for easier batch review
    by_rubric: dict[str, list[dict]] = defaultdict(list)
    for env in envelopes:
        rname = env["rubric"]["name"] or "unknown"
        by_rubric[rname].append(env)

    # Sort each rubric's envelopes by confidence DESC
    BOOTSTRAP_DIR.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict] = []
    total = 0
    for rubric_name, envs in sorted(by_rubric.items()):
        envs.sort(key=lambda e: -e["confidence"])
        # safe filename
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", rubric_name)[:80]
        write_jsonl(BOOTSTRAP_DIR / f"bootstrap_{safe}.jsonl", envs)
        total += len(envs)
        manifest_rows.append({
            "rubric": rubric_name,
            "candidates": len(envs),
            "high_confidence": sum(1 for e in envs if e["confidence"] >= 0.6),
            "file": f"inbox/bootstrap/bootstrap_{safe}.jsonl",
        })

    # Overall confidence distribution
    confs = [e["confidence"] for e in envelopes]
    high = sum(1 for c in confs if c >= 0.6)
    mid = sum(1 for c in confs if 0.3 <= c < 0.6)
    low = sum(1 for c in confs if c < 0.3)

    manifest = {
        "source": "criteria + eval_criteria_results + eval_runs",
        "results_total": len(results),
        "envelopes": total,
        "skipped_no_join": skipped,
        "rubrics": len(manifest_rows),
        "confidence": {"high_>=0.6": high, "mid_0.3-0.6": mid, "low_<0.3": low},
        "types": manifest_rows,
    }
    (REVIEW_DIR / "bootstrap_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"generated {total} bootstrap envelopes (skipped {skipped} no-join)")
    print(f"confidence: high(>=0.6)={high}  mid={mid}  low(<0.3)={low}")
    print(f"per-rubric batches: {BOOTSTRAP_DIR}")
    print(f"\ntop 10 rubrics by candidate count:")
    for r in sorted(manifest_rows, key=lambda x: -x["candidates"])[:10]:
        print(f"  {r['rubric']:<45} {r['candidates']:>4}  hi-conf={r['high_confidence']:>4}  {r['file']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="build review envelopes from eval history")
    p.set_defaults(func=cmd_build)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
