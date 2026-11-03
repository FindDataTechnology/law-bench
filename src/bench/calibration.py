"""Judge calibration machine: the judge's judge, as recorded data.

A domain-neutral device that measures how well an LLM judge's verdicts track
human verdicts, buckets the agreement by the judge's self-reported
confidence, checks that per-bucket accuracy is monotonic in confidence, and
persists the whole calibration as one ``eval_runs`` meta row
(``channel='meta'``, ``unit_kind='judge'``) so a "this judge is calibrated"
claim stays queryable instead of oral.

Inputs are paired gold records supplied by the caller — one dict per judged
item: ``{"confidence": float | None, "judge_verdict": bool, "human_verdict":
bool}`` (``confidence`` is the judge's self-reported confidence, e.g. parsed
from its reasoning; ``None`` when the judge did not report one). Nothing here
assumes a gold corpus exists on disk, and no judge/LLM is ever invoked:
calibration is pure arithmetic over the records plus one honest bookkeeping
insert via :func:`src.eval.store.store_result`.

Stored meta-run row contract (written and read back only by this module):

- ``rubric_name`` = ``judge-calibration:<judge_model>@<prompt_version>``
- ``score``       = the overall agree rate (judge_verdict == human_verdict)
- ``all_pass``    = 1 iff the agree rate meets ``CALIBRATION_MIN_AGREE`` AND
  per-bucket accuracy is monotonic in confidence
- ``summary``     = human-readable, embedding the machine-readable fragments
  ``n=<int>`` and ``monotonic=(yes|no)`` that :func:`is_calibrated` parses
  back
- one ``eval_criteria_results`` row per confidence bucket, verdict ``pass``
  iff that bucket is non-empty and its accuracy meets
  ``CALIBRATION_MIN_AGREE`` (a diagnostic; the run-level gate is ``all_pass``)
"""

from __future__ import annotations

import bisect
import re
from typing import Any, Optional

from src.settings import DEFAULT_DB

from src.eval.store import store_result

# Agree-rate bar a calibration run must meet (tunable).
CALIBRATION_MIN_AGREE = 0.70
# Tolerated single-step accuracy dip between adjacent confidence buckets
# (small-sample noise); a larger drop fails the monotonicity check.
MONOTONIC_TOLERANCE = 0.05
# Minimum number of paired gold records for a calibration to count as
# evidence (below this the run may pass its gates but proves too little).
CALIBRATION_MIN_SAMPLES = 50
# Default confidence bucket edges: intervals [e0,e1) ... [e(n-2),e(n-1)] —
# half-open except the last, which is closed so a confidence of exactly 1.0
# lands in the final bucket.
DEFAULT_BUCKET_EDGES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
# Records whose confidence is None (the judge did not self-report) are
# reported in this separate bucket and excluded from monotonicity.
NO_CONFIDENCE_BUCKET = "no-confidence"

# Machine-readable summary fragments (writer: run_calibration; reader:
# is_calibrated). ``n=(\d+)`` is anchored so it cannot match inside other
# ``...=`` fragments (e.g. ``agree_rate=``), and ``monotonic=`` is unique.
_N_FRAGMENT_RE = re.compile(r"(?:^|[\s;])n=(\d+)")
_MONO_FRAGMENT_RE = re.compile(r"monotonic=(yes|no)")


def _validate_records(records: Any) -> list[dict]:
    """Validate paired gold records; return normalized copies.

    Each record must be a dict with boolean ``judge_verdict`` and
    ``human_verdict``, and an optional ``confidence`` that is ``None`` or a
    number in [0, 1] (a missing key reads as ``None``). Raises ``ValueError``
    naming the offending record index — a malformed pair is a caller bug and
    must fail loudly, not skew the agree rate.
    """
    if isinstance(records, (str, bytes)) or not hasattr(records, "__iter__"):
        raise ValueError("gold_records must be an iterable of record dicts")
    validated: list[dict] = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise ValueError(
                f"gold record #{i} must be a dict, got {type(rec).__name__}"
            )
        for key in ("judge_verdict", "human_verdict"):
            if key not in rec:
                raise ValueError(f"gold record #{i} is missing {key!r}")
            if not isinstance(rec[key], bool):
                raise ValueError(f"gold record #{i}: {key!r} must be a bool")
        conf = rec.get("confidence")
        if conf is not None:
            if isinstance(conf, bool) or not isinstance(conf, (int, float)):
                raise ValueError(
                    f"gold record #{i}: 'confidence' must be a float or None"
                )
            if not 0.0 <= float(conf) <= 1.0:
                raise ValueError(
                    f"gold record #{i}: 'confidence' {conf} is outside [0, 1]"
                )
        validated.append(
            {
                "confidence": None if conf is None else float(conf),
                "judge_verdict": rec["judge_verdict"],
                "human_verdict": rec["human_verdict"],
            }
        )
    return validated


def _check_edges(bucket_edges: Any) -> tuple[float, ...]:
    """Validate bucket edges: >= 2 floats in [0, 1], strictly increasing."""
    try:
        edges = tuple(float(e) for e in bucket_edges)
    except (TypeError, ValueError):
        raise ValueError(f"bucket_edges must be numbers, got {bucket_edges!r}") from None
    if len(edges) < 2:
        raise ValueError("bucket_edges needs at least two edges")
    if any(not 0.0 <= e <= 1.0 for e in edges):
        raise ValueError(f"bucket_edges must lie within [0, 1]: {edges}")
    if any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError(f"bucket_edges must be strictly increasing: {edges}")
    return edges


def _fmt_edge(value: float) -> str:
    """Compact edge label: ``0.5`` / ``0.85`` / ``1.0`` (whole numbers keep .0)."""
    text = f"{value:g}"
    if "." not in text and "e" not in text:
        text += ".0"
    return text


def _bucket_labels(edges: tuple[float, ...]) -> list[str]:
    """Labels for the low catch-all plus one interval per adjacent edge pair."""
    labels = [f"<{_fmt_edge(edges[0])}"]
    last = len(edges) - 2
    for j, (a, b) in enumerate(zip(edges, edges[1:])):
        closing = "]" if j == last else ")"
        labels.append(f"[{_fmt_edge(a)},{_fmt_edge(b)}{closing}")
    return labels


def bucket_accuracy(
    records: list[dict], bucket_edges: tuple[float, ...] = DEFAULT_BUCKET_EDGES
) -> list[dict]:
    """Bucket records by self-reported confidence; report [bucket, n, accuracy].

    Returns one dict per bucket in ascending confidence order —
    ``{"bucket": label, "n": <count>, "accuracy": float | None}`` — followed
    by the separate ``no-confidence`` bucket for records whose confidence is
    ``None``. ``accuracy`` is the per-bucket agree rate (judge_verdict ==
    human_verdict) and is ``None`` for an empty bucket; every bucket is
    reported even when empty so the shape is stable across runs. Confidences
    below the lowest edge land in the leading ``<e0`` catch-all bucket.
    """
    edges = _check_edges(bucket_edges)
    validated = _validate_records(records)
    labels = _bucket_labels(edges)
    counts = [0] * len(labels)
    agrees = [0] * len(labels)
    no_conf_n = 0
    no_conf_agrees = 0

    for rec in validated:
        agrees_flag = rec["judge_verdict"] == rec["human_verdict"]
        if rec["confidence"] is None:
            no_conf_n += 1
            no_conf_agrees += agrees_flag
            continue
        # bisect_right gives the half-open [a, b) semantics for interior
        # edges; confidences at the top edge clamp into the closed last
        # interval, and anything below the lowest edge lands in bucket 0.
        idx = min(bisect.bisect_right(edges, rec["confidence"]), len(edges) - 1)
        counts[idx] += 1
        agrees[idx] += agrees_flag

    rows = [
        {
            "bucket": label,
            "n": n,
            "accuracy": (agrees[i] / n) if n else None,
        }
        for i, (label, n) in enumerate(zip(labels, counts))
    ]
    rows.append(
        {
            "bucket": NO_CONFIDENCE_BUCKET,
            "n": no_conf_n,
            "accuracy": (no_conf_agrees / no_conf_n) if no_conf_n else None,
        }
    )
    return rows


def monotonicity(
    buckets: list[dict], tolerance: float = MONOTONIC_TOLERANCE
) -> tuple[bool, str]:
    """Is per-bucket accuracy non-decreasing as self-reported confidence rises?

    Consumes :func:`bucket_accuracy` rows. Only non-empty confidence buckets
    carry an accuracy signal: the ``no-confidence`` bucket and empty buckets
    are skipped. Adjacent buckets may dip by up to ``tolerance`` (default
    ``MONOTONIC_TOLERANCE`` = 0.05) without failing; a larger drop names its
    step in the detail. Returns ``(ok, detail)``; with fewer than two
    non-empty buckets the check is vacuously true and says so.
    """
    if not isinstance(buckets, list):
        raise ValueError("buckets must be bucket_accuracy()'s row list")
    steps = [
        (row["bucket"], row["accuracy"])
        for row in buckets
        if row.get("bucket") != NO_CONFIDENCE_BUCKET and row.get("n", 0) > 0
    ]
    if len(steps) < 2:
        names = ", ".join(name for name, _ in steps) or "none"
        return True, (
            f"monotonicity not testable: {len(steps)} non-empty confidence "
            f"bucket(s) ({names}); need at least 2"
        )
    for (name_a, acc_a), (name_b, acc_b) in zip(steps, steps[1:]):
        if acc_b < acc_a - tolerance:
            return False, (
                f"accuracy drops {acc_a:.4f} -> {acc_b:.4f} at bucket {name_b} "
                f"(tolerance {tolerance:g})"
            )
    sequence = " -> ".join(f"{name}={acc:.4f}" for name, acc in steps)
    return True, (
        f"accuracy is non-decreasing across {len(steps)} non-empty buckets "
        f"(tolerance {tolerance:g}): {sequence}"
    )


def run_calibration(
    conn: Any,
    *,
    judge_model: str,
    prompt_version: str,
    gold_records: list[dict],
    db_path: Any = DEFAULT_DB,
) -> dict:
    """Score one judge+prompt version against paired gold records and store it.

    Computes the overall agree rate, the per-confidence-bucket accuracy
    matrix, and the monotonicity of that matrix, then stores one meta run —
    ``channel='meta'``, ``unit_kind='judge'``,
    ``rubric_name='judge-calibration:<judge_model>@<prompt_version>'``,
    ``judge_model`` as given, ``score=agree_rate``, ``max_score=1.0``,
    ``all_pass`` set only when the agree rate meets ``CALIBRATION_MIN_AGREE``
    and the buckets are monotonic, and one criteria row per bucket — via
    :func:`src.eval.store.store_result` on ``db_path`` (which may be a live
    connection, as everywhere else).

    ``conn`` is accepted for call-site symmetry with the other bench entry
    points; calibration reads nothing from the knowledge-unit store (the gold
    records come from the caller), so it is not otherwise used.

    ``gold_records`` must be non-empty (a zero-record calibration would be a
    vacuous claim — raise instead). Returns the full result dict: run_id,
    rubric, judge_model, prompt_version, n, agrees, agree_rate, buckets,
    monotonic, monotonic_detail, all_pass, min_agree.
    """
    if not isinstance(judge_model, str) or not judge_model.strip():
        raise ValueError("judge_model must be a non-empty string")
    if not isinstance(prompt_version, str) or not prompt_version.strip():
        raise ValueError("prompt_version must be a non-empty string")
    validated = _validate_records(gold_records)
    if not validated:
        raise ValueError(
            "gold_records is empty: calibration needs paired judge/human verdicts"
        )

    n = len(validated)
    agrees = sum(1 for r in validated if r["judge_verdict"] == r["human_verdict"])
    agree_rate = agrees / n

    buckets = bucket_accuracy(validated, DEFAULT_BUCKET_EDGES)
    mono_ok, mono_detail = monotonicity(buckets)
    all_pass = bool(mono_ok and agree_rate >= CALIBRATION_MIN_AGREE)

    criteria_results = []
    for row in buckets:
        passed = row["n"] > 0 and row["accuracy"] >= CALIBRATION_MIN_AGREE
        criteria_results.append(
            {
                "id": f"bucket:{row['bucket']}",
                "title": row["bucket"],
                "verdict": "pass" if passed else "fail",
                "reasoning": (
                    f"n={row['n']}, accuracy={row['accuracy']:.4f}"
                    if row["n"]
                    else "n=0, empty bucket (no signal)"
                ),
            }
        )

    rubric_name = f"judge-calibration:{judge_model}@{prompt_version}"
    run_id = store_result(
        {
            "rubric": rubric_name,
            "score": agree_rate,
            "max_score": 1.0,
            "all_pass": all_pass,
            "n_criteria": len(criteria_results),
            "n_passed": sum(1 for c in criteria_results if c["verdict"] == "pass"),
            "summary": (
                f"judge calibration: n={n} paired records, "
                f"agree_rate={agree_rate:.4f} "
                f"(min {CALIBRATION_MIN_AGREE:.2f}), "
                f"monotonic={'yes' if mono_ok else 'no'}; {mono_detail}"
            ),
            "judge_model": judge_model,
            "criteria_results": criteria_results,
        },
        task_desc=f"prompt_version={prompt_version}",
        db_path=db_path,
        channel="meta",
        unit_kind="judge",
    )

    return {
        "run_id": run_id,
        "rubric": rubric_name,
        "judge_model": judge_model,
        "prompt_version": prompt_version,
        "n": n,
        "agrees": agrees,
        "agree_rate": agree_rate,
        "buckets": buckets,
        "monotonic": mono_ok,
        "monotonic_detail": mono_detail,
        "all_pass": all_pass,
        "min_agree": CALIBRATION_MIN_AGREE,
    }


def is_calibrated(
    conn: Any,
    *,
    judge_model: str,
    prompt_version: str,
    db_path: Any = DEFAULT_DB,
) -> tuple[bool, str]:
    """Has this judge+prompt version passed a stored calibration run?

    Looks up the most recent ``judge-calibration:<judge_model>@<prompt_version>``
    meta run (queried on ``conn``, the caller's handle; ``db_path`` is kept
    for call-site symmetry with :func:`run_calibration` and is not used on the
    read path). Calibrated iff that run's ``all_pass`` is set — agree rate at
    or above ``CALIBRATION_MIN_AGREE`` and monotonic buckets — AND it scored
    at least ``CALIBRATION_MIN_SAMPLES`` paired gold records (the record
    count is parsed from the run's ``summary``, the writer's own format).

    Returns ``(ok, reason)``; the reason always names which path applies: no
    calibration run / not enough samples / gates not met (agree rate or
    monotonicity).
    """
    rubric_name = f"judge-calibration:{judge_model}@{prompt_version}"
    row = conn.execute(
        "SELECT id, score, all_pass, summary FROM eval_runs "
        "WHERE rubric_name = %s AND judge_model = %s "
        "  AND channel = 'meta' AND unit_kind = 'judge' "
        "ORDER BY id DESC LIMIT 1",
        (rubric_name, judge_model),
    ).fetchone()
    if row is None:
        return False, (
            f"no calibration run found for judge '{judge_model}' "
            f"@ prompt version '{prompt_version}'"
        )

    summary = row["summary"] or ""
    n_match = _N_FRAGMENT_RE.search(summary)
    mono_match = _MONO_FRAGMENT_RE.search(summary)
    n: Optional[int] = int(n_match.group(1)) if n_match else None

    if not bool(row["all_pass"]):
        if float(row["score"]) < CALIBRATION_MIN_AGREE:
            return False, (
                f"calibration run {row['id']} not passed: agree_rate "
                f"{float(row['score']):.4f} is below the required "
                f"{CALIBRATION_MIN_AGREE:.2f} "
                f"(n={n if n is not None else 'unknown'})"
            )
        return False, (
            f"calibration run {row['id']} not passed: per-bucket accuracy is "
            f"not monotonic in confidence"
            + (f" (monotonic={mono_match.group(1)})" if mono_match else "")
        )

    if n is None:
        return False, (
            f"calibration run {row['id']} passed its gates but its summary is "
            f"missing the machine-readable record count (n=<int>)"
        )
    if n < CALIBRATION_MIN_SAMPLES:
        return False, (
            f"calibration run {row['id']} passed its gates but scored only "
            f"n={n} paired gold records (minimum {CALIBRATION_MIN_SAMPLES})"
        )
    return True, (
        f"calibration run {row['id']}: agree_rate {float(row['score']):.4f} "
        f">= {CALIBRATION_MIN_AGREE:.2f}, "
        f"monotonic={mono_match.group(1) if mono_match else 'yes'}, "
        f"n={n} >= {CALIBRATION_MIN_SAMPLES}"
    )
