#!/usr/bin/env python3
"""Live judge calibration against human-gold pairs (task 4.1/4.2 + channel
selection bake-off, add-judge-model-selection).

Re-judges a human-gold pair set with the CURRENT judge prompt
(``EVAL_PROMPT_VERSION``, v2-structure: role separation, injection defense,
field discipline, trailing CONFIDENCE self-report) and stores one meta
calibration run via ``src.bench.calibration.run_calibration``.

Confidence channel (``--samples k``): the GEval/deepeval chain systematically
suppressed the self-reported CONFIDENCE tail marker (105/108 missing, twice
reproduced), so with k>1 each item is judged k independent times at a positive
sampling temperature and confidence = the majority vote share. With k=1 the
legacy self-report parse is kept but explicitly marked as no channel
(``confidence_source="none"``) — a channel failure never silently degrades
to an undeclared confidence value.

Input gold file: JSON list of pairs, each::

    {"pair_id": ..., "guidance": <criterion guidance>, "draft_text": <doc>,
     "human_pass": bool, "judge_pass": <legacy judge verdict, informational>}

Pairs come from the prod review pilot export (double-annotated, agreement-QC'd).
Usage::

    uv run python scripts/calibrate_judge_live.py --gold /tmp/gold_validity_pilot.json
    uv run python scripts/calibrate_judge_live.py --gold /tmp/gold_validity_pilot.json \
        --samples 5 --candidate flash-vote-k5

Env: OPENAI_API_KEY / OPENAI_API_BASE / EVAL_MODEL (see .env),
JUDGE_SAMPLING_TEMPERATURE for the vote-share channel (default 0.7, only
used when k>1), database_url for the local platform DB where the meta run is
stored.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

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

DEFAULT_SAMPLES = 5
DEFAULT_SAMPLING_TEMPERATURE = 0.7

# GEval generates its evaluation steps with a separate LLM call per metric
# instance. The steps depend only on the criterion text, so caching them per
# distinct guidance halves the calls in a k-sample bake-off (51 distinct
# criteria in the 108-pair pilot gold). Cache lives for one driver process.
_STEPS_CACHE: dict[str, list[str]] = {}


def _evaluation_steps_for(criteria: str, judge) -> Optional[list[str]]:
    """Generate (once per process) the GEval steps for a criterion guidance.

    Returns ``None`` when step generation itself fails (relay timeout etc.)
    so the caller falls back to GEval's own per-instance generation instead
    of caching a broken probe. Failure is never silently turned into a fake
    verdict.
    """
    if criteria in _STEPS_CACHE:
        return _STEPS_CACHE[criteria]
    try:
        probe = GEval(
            name="steps-probe",
            criteria=criteria,
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            strict_mode=True,
            model=judge,
            async_mode=False,
        )
        steps = probe._generate_evaluation_steps(False)
    except Exception as e:  # noqa: BLE001 - relay failures must not kill the run
        print(
            f"evaluation-steps probe failed for one criterion: "
            f"{type(e).__name__}: {str(e)[:160]}",
            flush=True,
        )
        return None
    _STEPS_CACHE[criteria] = steps
    return steps


def _score_pair_once(pair: dict, judge) -> dict:
    """One judge call: does the document pass this criterion's guidance?"""
    criteria = build_judge_criteria(pair["guidance"])
    metric = GEval(
        name=str(pair.get("pair_id", "")),
        criteria=criteria,
        evaluation_steps=_evaluation_steps_for(criteria, judge),
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


def _aggregate(pair: dict, attempts: list[dict], samples: int) -> dict:
    """Aggregate k independent attempts into one vote-share gold record.

    All-failed items are returned with ``dropped=True`` — they must never
    become a fabricated fail verdict. Partial failures keep the successful
    votes (confidence denominator = number of successful attempts) and are
    counted in ``n_sample_errors``; a failure never silently becomes a
    confidence value.
    """
    ok = [a for a in attempts if not a["call_error"]]
    errors = [a["call_error"][:200] for a in attempts if a["call_error"]]
    rec: dict[str, Any] = {
        "pair_id": pair.get("pair_id"),
        "criterion_id": pair.get("criterion_id"),
        "human_verdict": bool(pair["human_pass"]),
        "legacy_judge_verdict": pair.get("judge_pass"),
        "reasoning": ok[0]["reasoning"] if ok else None,
        "votes": [a["judge_verdict"] for a in ok],
        "n_sample_errors": len(errors),
        "sample_errors": errors,
        "call_error": ok[0].get("call_error") if ok else (errors[0] if errors else None),
        "confidence_source": "none",
        "confidence": None,
        "judge_verdict": False,
        "dropped": not ok,
    }
    if samples > 1 and ok:
        pass_count = sum(rec["votes"])
        fail_count = len(ok) - pass_count
        # k is constrained odd by main(); no tie is possible over successful
        # votes of an odd total. With partial failures, a tie is broken by
        # the fail side (conservative, and flagged in sample_errors).
        rec["judge_verdict"] = pass_count > fail_count
        rec["confidence"] = max(pass_count, fail_count) / len(ok)
        rec["confidence_source"] = "vote_share"
    elif ok:
        single = ok[0]
        rec["judge_verdict"] = single["judge_verdict"]
        rec["confidence"] = single["confidence"]
    return rec


def _score_pair(pair: dict, judge, samples: int = 1) -> dict:
    """k independent attempts, then vote-share aggregation (k=1 = legacy).

    An exception escaping a relay/deepeval call is converted into k failed
    attempts (all dropped) rather than killing the whole calibration run —
    the item is honestly recorded as unusable, never as a fabricated verdict.
    """
    try:
        attempts = [_score_pair_once(pair, judge) for _ in range(samples)]
    except Exception as e:  # noqa: BLE001 - one bad item must not abort 108 pairs
        return {
            "pair_id": pair.get("pair_id"),
            "criterion_id": pair.get("criterion_id"),
            "human_verdict": bool(pair["human_pass"]),
            "legacy_judge_verdict": pair.get("judge_pass"),
            "reasoning": None,
            "votes": [],
            "n_sample_errors": samples,
            "sample_errors": [f"{type(e).__name__}: {str(e)[:160]}"] * samples,
            "call_error": f"{type(e).__name__}: {str(e)[:160]}",
            "confidence_source": "none",
            "confidence": None,
            "judge_verdict": False,
            "dropped": True,
        }
    return _aggregate(pair, attempts, samples)


def _sampling_temperature() -> float:
    raw = os.getenv("JUDGE_SAMPLING_TEMPERATURE", str(DEFAULT_SAMPLING_TEMPERATURE))
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"JUDGE_SAMPLING_TEMPERATURE must be a number, got {raw!r}")
    if not 0.0 < value <= 2.0:
        raise ValueError(
            f"JUDGE_SAMPLING_TEMPERATURE must be in (0, 2], got {value}"
        )
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True, help="path to gold pairs JSON")
    ap.add_argument("--out", default="/tmp/calibration_records.json")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="0 = all pairs")
    ap.add_argument(
        "--samples", type=int, default=DEFAULT_SAMPLES,
        help="independent judge calls per item (odd, >=1); k=1 marks no channel",
    )
    ap.add_argument(
        "--candidate", default="",
        help="bake-off candidate label (defaults to EVAL_MODEL)",
    )
    args = ap.parse_args()

    k = args.samples
    if k < 1 or k % 2 == 0:
        ap.error("--samples must be an odd integer >= 1 (no tied votes)")
    load_dotenv()
    pairs = json.loads(Path(args.gold).read_text())
    if args.limit:
        pairs = pairs[: args.limit]
    candidate = args.candidate or os.environ.get("EVAL_MODEL", "unknown")
    print(f"pairs: {len(pairs)} | judge prompt: {EVAL_PROMPT_VERSION} "
          f"| model: {os.environ.get('EVAL_MODEL')} "
          f"| samples: {k} | candidate: {candidate}", flush=True)

    judge = get_judge()
    if k > 1:
        # A vote-share channel needs dispersion; the default judge temperature
        # is 0.0 (deterministic), which would make k samples identical votes.
        judge.temperature = _sampling_temperature()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(
            pool.map(lambda p: _score_pair(p, judge, k), pairs)
        )

    dropped = [r for r in records if r["dropped"]]
    Path(args.out).write_text(json.dumps(records, ensure_ascii=False, indent=1))
    usable = [r for r in records if not r["dropped"]]
    errors = sum(r["n_sample_errors"] for r in records)
    agree = sum(1 for r in usable if r["judge_verdict"] == r["human_verdict"])
    print(f"scored: {len(records)} (dropped all-failed items: {len(dropped)}, "
          f"sample call errors: {errors}) | "
          f"agree: {agree}/{len(usable)} = {agree / max(1, len(usable)):.3f}")
    if dropped:
        print("dropped pair_ids:", [r["pair_id"] for r in dropped], flush=True)
    if not usable:
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
             "human_verdict": r["human_verdict"],
             "confidence_source": r["confidence_source"]}
            for r in usable
        ],
        candidate=candidate,
        samples=k,
        n_calls=len(pairs) * k,
    )
    conn.close()
    print("calibration run id:", result.get("run_id"))
    print(json.dumps({key: result[key] for key in
                      ("agree_rate", "balanced_accuracy", "kappa",
                       "all_pass", "n")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
