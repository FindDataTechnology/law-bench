#!/usr/bin/env python3
"""Live judge calibration against human-gold pairs (task 4.1/4.2).

Re-judges a human-gold pair set with the CURRENT judge prompt
(``EVAL_PROMPT_VERSION``, v2-structure: role separation, injection defense,
field discipline, trailing CONFIDENCE self-report) and stores one meta
calibration run via ``src.bench.calibration.run_calibration``.

Input gold file: JSON list of pairs, each::

    {"pair_id": ..., "guidance": <criterion guidance>, "draft_text": <doc>,
     "human_pass": bool, "judge_pass": <legacy judge verdict, informational>}

Pairs come from the prod review pilot export (double-annotated, agreement-QC'd).
Usage::

    uv run python scripts/calibrate_judge_live.py --gold /tmp/gold_validity_pilot.json

Env: OPENAI_API_KEY / OPENAI_API_BASE / EVAL_MODEL (see .env), database_url for
the local platform DB where the meta run is stored.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from deepeval.test_case import LLMTestCase, LLMTestCaseParams  # noqa: E402
from deepeval.metrics import GEval  # noqa: E402

from src.bench.calibration import run_calibration  # noqa: E402
from src.eval.db import connect  # noqa: E402
from src.eval.judge import get_judge  # noqa: E402
from src.eval.scoring import (  # noqa: E402
    EVAL_PROMPT_VERSION,
    build_judge_criteria,
    parse_confidence,
)


def _score_pair(pair: dict, judge) -> dict:
    """One judge call: does the document pass this criterion's guidance?"""
    metric = GEval(
        name=str(pair.get("pair_id", "")),
        criteria=build_judge_criteria(pair["guidance"]),
        evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
        strict_mode=True,
        model=judge,
        async_mode=False,
    )
    test_case = LLMTestCase(input="", actual_output=pair["draft_text"])
    last_err = None
    for attempt in range(3):
        try:
            metric.measure(test_case, _show_indicator=False)
            break
        except Exception as e:  # noqa: BLE001 - mirror scoring.py retry policy
            s = str(e)
            last_err = s
            if ("RateLimit" in s or "429" in s or "ServiceUnavailable" in s
                    or "503" in s) and attempt < 2:
                time.sleep(8 * (attempt + 1))
                continue
            break
    reason = getattr(metric, "reason", "") or ""
    err = getattr(metric, "error", None)
    if err:
        reason = f"{reason} [error: {err}]".strip()
    return {
        "pair_id": pair.get("pair_id"),
        "criterion_id": pair.get("criterion_id"),
        "judge_verdict": bool(getattr(metric, "success", False)),
        "human_verdict": bool(pair["human_pass"]),
        "confidence": parse_confidence(reason),
        "legacy_judge_verdict": pair.get("judge_pass"),
        "reasoning": reason[:400],
        "call_error": last_err if err else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True, help="path to gold pairs JSON")
    ap.add_argument("--out", default="/tmp/calibration_records.json")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="0 = all pairs")
    args = ap.parse_args()

    load_dotenv()
    pairs = json.loads(Path(args.gold).read_text())
    if args.limit:
        pairs = pairs[: args.limit]
    print(f"pairs: {len(pairs)} | judge prompt: {EVAL_PROMPT_VERSION} "
          f"| model: {os.environ.get('EVAL_MODEL')}", flush=True)

    judge = get_judge()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(lambda p: _score_pair(p, judge), pairs))

    Path(args.out).write_text(json.dumps(records, ensure_ascii=False, indent=1))
    errors = sum(1 for r in records if r["call_error"])
    agree = sum(1 for r in records if r["judge_verdict"] == r["human_verdict"])
    print(f"scored: {len(records)} (call errors: {errors}) | "
          f"agree: {agree}/{len(records)} = {agree / max(1, len(records)):.3f}")
    if errors == len(records):
        print("all calls failed - not storing a calibration run")
        return 1

    conn = connect()
    result = run_calibration(
        conn,
        judge_model=os.environ.get("EVAL_MODEL", "unknown"),
        prompt_version=EVAL_PROMPT_VERSION,
        gold_records=[
            {"confidence": r["confidence"],
             "judge_verdict": r["judge_verdict"],
             "human_verdict": r["human_verdict"]}
            for r in records
        ],
    )
    conn.close()
    print("calibration run id:", result.get("run_id"))
    print(json.dumps({k: result[k] for k in
                      ("agree_rate", "monotonic", "all_pass", "n")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
