#!/usr/bin/env python3
"""CLI: evaluate a drafted contract against a rubric.

Mirrors running `harbor`/harvey-labs scoring over a single contract, writing a
harvey-labs-shaped scores.json. Uses deepeval's native GEval judge.

Examples:
  # evaluate an existing draft
  python -m src.eval.run --contract output/service-agreement-draft.md \\
      --rubric contract_drafting_v1

  # with the original user request as task context (richer judging)
  python -m src.eval.run --contract output/service-agreement-draft.md \\
      --rubric contract_drafting_v1 --task "起草一份服务协议，甲方为科技公司..."

  python -m src.eval.run --list-rubrics
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    # Legal contract text must not leave the machine: opt out of deepeval telemetry.
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "true")

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--contract", type=Path, help="Path to the drafted contract file.")
    ap.add_argument("--rubric", help="Rubric name (e.g. contract_drafting_v1).")
    ap.add_argument("--task", default=None, help="Original user request (optional context).")
    ap.add_argument("--out", type=Path, default=None, help="scores.json output path.")
    ap.add_argument("--verbose", action="store_true", help="Verbose judge output.")
    ap.add_argument("--list-rubrics", action="store_true", help="List available rubrics and exit.")
    ap.add_argument("--list-runs", action="store_true", help="List recent evaluation runs from the DB and exit.")
    ap.add_argument("--no-store", action="store_true", help="Do not persist the run to the DB (JSON only).")
    args = ap.parse_args()

    if args.list_rubrics:
        from .rubric import list_rubrics

        print(f"{'name':24} {'context':10} source")
        print("-" * 60)
        for r in list_rubrics():
            print(f"{r['name']:24} {r['context']:10} {r['source']}")
        return 0

    if args.list_runs:
        from .store import list_runs

        runs = list_runs()
        if not runs:
            print("(no evaluation runs stored yet)")
            return 0
        print(f"{'id':>3}  {'rubric':24} {'contract':38} {'score':>5} {'result':6} {'n':>5} {'judge':10} {'scored_at'}")
        print("-" * 110)
        for r in runs:
            contract = (r["contract_path"] or "")
            print(
                f"{r['id']:>3}  {r['rubric_name']:24} {contract[:38]:38} "
                f"{r['score']:>5.1f} {'PASS' if r['all_pass'] else 'FAIL':6} "
                f"{r['n_passed']}/{r['n_criteria']:<3} {r['judge_model'] or '':10} {r['scored_at']}"
            )
        return 0

    if not args.contract or not args.rubric:
        ap.error("--contract and --rubric are required (or use --list-rubrics)")

    if not args.contract.is_file():
        print(f"Error: contract not found: {args.contract}", file=sys.stderr)
        return 2

    contract_text = args.contract.read_text(encoding="utf-8")

    from .scoring import evaluate_contract

    try:
        result = evaluate_contract(
            contract_text=contract_text,
            rubric_name=args.rubric,
            task_desc=args.task,
            verbose=args.verbose,
        )
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Evaluation failed: {e}", file=sys.stderr)
        return 3

    out_path = args.out or (
        Path("output/eval") / f"{args.rubric}_{args.contract.stem}_scores.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    run_id = None
    if not args.no_store:
        from .store import store_result

        run_id = store_result(
            result,
            contract_path=str(args.contract),
            task_desc=args.task,
        )

    print("=" * 60)
    print(f"Rubric   : {result['rubric']}")
    print(f"Contract : {args.contract}")
    print(f"Judge    : {result['judge_model']}")
    print(f"Score    : {result['score']:.1f}/{result['max_score']:.1f}  "
          f"({'ALL PASS' if result['all_pass'] else 'FAIL'})")
    print(f"Criteria : {result['n_passed']}/{result['n_criteria']} passed")
    print("-" * 60)
    for c in result["criteria_results"]:
        mark = "✓" if c["verdict"] == "pass" else "✗"
        print(f"  {mark} [{c['verdict']}] {c['id']}: {c['title']}")
        if c["reasoning"]:
            print(f"      {c['reasoning'].strip()[:280]}")
    print("=" * 60)
    print(f"Scores written to: {out_path}")
    if run_id is not None:
        print(f"DB run id : {run_id}  (stored in db/evaluation_rules.db)")
    else:
        print("DB run id : skipped (--no-store)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
