"""Judge calibration machine: the judge's judge, as recorded data.

A domain-neutral device that measures how well an LLM judge's verdicts track
human verdicts, buckets the agreement by the confidence channel's per-record
confidence, checks that per-bucket accuracy is monotonic in confidence, and
persists the whole calibration as one ``eval_runs`` meta row
(``channel='meta'``, ``unit_kind='judge'``) so a "this judge is calibrated"
claim stays queryable instead of oral.

Inputs are paired gold records supplied by the caller — one dict per judged
item: ``{"confidence": float | None, "judge_verdict": bool, "human_verdict":
bool, "confidence_source": str | None}``. ``confidence`` comes from whatever
channel the caller declared (e.g. ``vote_share`` for repeated-sampling
agreement, recorded per-record in ``confidence_source``; ``None`` when the
channel produced none). Nothing here assumes a gold corpus exists on disk,
and no judge/LLM is ever invoked: calibration is pure arithmetic over the
records plus one honest bookkeeping insert via
:func:`src.eval.store.store_result`.

Stored meta-run row contract (written and read back only by this module):

- ``rubric_name`` = ``judge-calibration:<judge_model>@<prompt_version>``
- ``score``       = the overall agree rate (judge_verdict == human_verdict)
  — a diagnostic only since the stratified gate landed
- ``all_pass``    = 1 iff balanced accuracy (mean of sensitivity and
  specificity over the human-verdict strata) meets ``CALIBRATION_MIN_AGREE``
  AND per-bucket accuracy is monotonic in channel confidence. Balanced
  accuracy keeps the gate immune to class-imbalanced gold (a judge that
  fails everything scores specificity 1.0 but balanced ≈ 0.5).
- ``summary``     = human-readable, embedding the machine-readable fragments
  ``n=<int>``, ``monotonic=(yes|no)`` and ``balanced_accuracy=<x|none>``
  that :func:`is_calibrated` parses back
- criteria rows: one stratified-gate row (``stratified:balanced_accuracy``)
  followed by one row per confidence bucket, verdict ``pass`` iff that
  bucket is non-empty and its accuracy meets ``CALIBRATION_MIN_AGREE``
  (the bucket rows are diagnostics; the run-level gate is ``all_pass``)
"""

from __future__ import annotations

import bisect
import re
from typing import Any, Optional

from src.settings import DEFAULT_DB

from . import verdicts
from src.eval.store import store_result

# Balanced-accuracy bar a calibration run must meet (tunable; historically
# the global agree-rate bar — same number, class-balanced semantics).
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
# Records whose confidence is None (the channel produced none) are
# reported in this separate bucket and excluded from monotonicity.
NO_CONFIDENCE_BUCKET = "no-confidence"

# Machine-readable summary fragments (writer: run_calibration; reader:
# is_calibrated). ``n=(\d+)`` is anchored so it cannot match inside other
# ``...=`` fragments (e.g. ``agree_rate=``), and ``monotonic=`` is unique.
_N_FRAGMENT_RE = re.compile(r"(?:^|[\s;])n=(\d+)")
_MONO_FRAGMENT_RE = re.compile(r"monotonic=(yes|no)")
_BAL_ACC_FRAGMENT_RE = re.compile(
    r"balanced_accuracy=(none|[01](?:\.\d+)?(?:[eE]-?\d+)?)"
)


def _validate_records(records: Any) -> list[dict]:
    """Validate paired gold records; return normalized copies.

    Each record must be a dict with boolean ``judge_verdict`` and
    ``human_verdict``, an optional ``confidence`` that is ``None`` or a
    number in [0, 1] (a missing key reads as ``None``), and an optional
    ``confidence_source`` that is ``None`` or a non-empty string naming the
    channel that produced the confidence (e.g. ``vote_share``). Raises
    ``ValueError`` naming the offending record index — a malformed pair is a
    caller bug and must fail loudly, not skew the agree rate.
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
        source = rec.get("confidence_source")
        if source is not None and (
            not isinstance(source, str) or not source.strip()
        ):
            raise ValueError(
                f"gold record #{i}: 'confidence_source' must be a non-empty "
                f"string or None, got {source!r}"
            )
        validated.append(
            {
                "confidence": None if conf is None else float(conf),
                "judge_verdict": rec["judge_verdict"],
                "human_verdict": rec["human_verdict"],
                "confidence_source": source,
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


def confusion_matrix(records: list[dict]) -> dict:
    """Human-verdict stratified confusion matrix over paired gold records.

    ``human_verdict=True`` is the positive class: ``tp`` counts judge-pass /
    human-pass, ``fn`` judge-fail / human-pass, ``fp`` judge-pass / human-fail,
    ``tn`` judge-fail / human-fail. Derived metrics:

    - ``sensitivity``   = tp/(tp+fn), ``None`` when the gold has no positives
    - ``specificity``   = tn/(tn+fp), ``None`` when the gold has no negatives
    - ``balanced_accuracy`` = (sensitivity+specificity)/2, ``None`` when
      either stratum is empty (single-class gold cannot produce a
      class-balanced score; the run-level gate fails on ``None``)
    - ``kappa``         = Cohen's kappa (chance-corrected agreement),
      ``None`` when n=0 or the expected agreement is degenerate (pe=1)

    ``None`` means "not definable on this data" — never a silent stand-in
    value that would flatter a degenerate judge (an all-fail judge on
    imbalanced gold keeps specificity 1.0 but balanced accuracy ~0.5).
    Accepts raw or :func:`_validate_records`-shaped records (validates
    internally); an empty input returns all-zero counts with every derived
    metric ``None``.
    """
    validated = _validate_records(records)
    tp = sum(
        1 for r in validated if r["human_verdict"] and r["judge_verdict"]
    )
    fn = sum(
        1 for r in validated if r["human_verdict"] and not r["judge_verdict"]
    )
    fp = sum(
        1 for r in validated if not r["human_verdict"] and r["judge_verdict"]
    )
    tn = sum(
        1 for r in validated
        if not r["human_verdict"] and not r["judge_verdict"]
    )
    n = len(validated)

    sensitivity = (tp / (tp + fn)) if (tp + fn) else None
    specificity = (tn / (tn + fp)) if (tn + fp) else None
    if sensitivity is None or specificity is None:
        balanced_accuracy: Optional[float] = None
    else:
        balanced_accuracy = (sensitivity + specificity) / 2

    kappa: Optional[float] = None
    if n:
        po = (tp + tn) / n
        # Chance agreement from the verdict marginals; pe=1 (degenerate
        # marginals, e.g. both sides constant) makes kappa 0/0.
        pe = (
            (tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)
        ) / (n * n)
        if pe != 1.0:
            kappa = (po - pe) / (1.0 - pe)

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "sensitivity": sensitivity,
        "specificity": specificity,
        "balanced_accuracy": balanced_accuracy,
        "kappa": kappa,
    }


def run_calibration(
    conn: Any,
    *,
    judge_model: str,
    prompt_version: str,
    gold_records: list[dict],
    db_path: Any = DEFAULT_DB,
    candidate: str = "",
    samples: int = 1,
    n_calls: Optional[int] = None,
) -> dict:
    """Score one judge+prompt version against paired gold records and store it.

    Computes the human-stratified confusion matrix (balanced accuracy gate),
    the overall agree rate (diagnostic), the per-confidence-bucket accuracy
    matrix, and the monotonicity of that matrix, then stores one meta run —
    ``channel='meta'``, ``unit_kind='judge'``,
    ``rubric_name='judge-calibration:<judge_model>@<prompt_version>'``,
    ``judge_model`` as given, ``score=agree_rate`` (diagnostic),
    ``max_score=1.0``, ``all_pass`` set only when balanced accuracy meets
    ``CALIBRATION_MIN_AGREE`` and the buckets are monotonic — via
    :func:`src.eval.store.store_result` on ``db_path`` (which may be a live
    connection, as everywhere else).

    Bake-off provenance: ``candidate`` labels the channel/model combination
    under test, ``samples`` the per-item sampling count behind a vote-share
    confidence channel, and ``n_calls`` the total judge calls spent; all
    three land in the run summary and task description so run rows stay
    comparable without touching the schema. Selection evidence only — a
    stored run never reconfigures the production judge.

    ``conn`` is accepted for call-site symmetry with the other bench entry
    points; calibration reads nothing from the knowledge-unit store (the gold
    records come from the caller), so it is not otherwise used.

    ``gold_records`` must be non-empty (a zero-record calibration would be a
    vacuous claim — raise instead). Returns the full result dict: run_id,
    rubric, judge_model, prompt_version, candidate, samples, n_calls, n,
    agrees, agree_rate, matrix, balanced_accuracy, kappa, buckets,
    monotonic, monotonic_detail, all_pass, min_agree.
    """
    if not isinstance(judge_model, str) or not judge_model.strip():
        raise ValueError("judge_model must be a non-empty string")
    if not isinstance(prompt_version, str) or not prompt_version.strip():
        raise ValueError("prompt_version must be a non-empty string")
    if candidate and (not isinstance(candidate, str) or not candidate.strip()):
        raise ValueError("candidate must be a non-empty string or empty")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError(f"samples must be an int >= 1, got {samples!r}")
    if n_calls is not None and (
        isinstance(n_calls, bool) or not isinstance(n_calls, int) or n_calls < 0
    ):
        raise ValueError(f"n_calls must be a non-negative int or None, got {n_calls!r}")
    validated = _validate_records(gold_records)
    if not validated:
        raise ValueError(
            "gold_records is empty: calibration needs paired judge/human verdicts"
        )

    n = len(validated)
    agrees = sum(1 for r in validated if r["judge_verdict"] == r["human_verdict"])
    agree_rate = agrees / n

    matrix = confusion_matrix(validated)
    balanced_accuracy = matrix["balanced_accuracy"]
    buckets = bucket_accuracy(validated, DEFAULT_BUCKET_EDGES)
    mono_ok, mono_detail = monotonicity(buckets)
    # Stratified gate: balanced accuracy over human-verdict strata (None =
    # single-class gold, an undefinable class-balanced score → gate fails)
    # AND channel-confidence buckets monotonic. The no-confidence bucket is
    # excluded from monotonicity by construction and can never pass the run.
    all_pass = bool(
        balanced_accuracy is not None
        and balanced_accuracy >= CALIBRATION_MIN_AGREE
        and mono_ok
    )

    if balanced_accuracy is None:
        gate_reasoning = (
            f"balanced_accuracy=none (single-class gold: "
            f"sensitivity={matrix['sensitivity']}, "
            f"specificity={matrix['specificity']}), kappa="
            f"{matrix['kappa'] if matrix['kappa'] is not None else 'none'}"
        )
    else:
        gate_reasoning = (
            f"balanced_accuracy={balanced_accuracy:.4f} "
            f"(min {CALIBRATION_MIN_AGREE:.2f}), "
            f"sensitivity={matrix['sensitivity']:.4f}, "
            f"specificity={matrix['specificity']:.4f}, kappa="
            f"{matrix['kappa'] if matrix['kappa'] is not None else 'none'}"
        )
    criteria_results = [
        {
            "id": "stratified:balanced_accuracy",
            "title": "balanced accuracy (gate)",
            "verdict": (
                "pass"
                if balanced_accuracy is not None
                and balanced_accuracy >= CALIBRATION_MIN_AGREE
                else "fail"
            ),
            "reasoning": gate_reasoning,
        }
    ]
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
    ba_fragment = (
        "none" if balanced_accuracy is None else f"{balanced_accuracy:.4f}"
    )
    provenance = (
        f"candidate={candidate}, " if candidate else ""
    ) + f"samples={samples}"
    if n_calls is not None:
        provenance += f", calls={n_calls}"

    # ── verdict-ledger shape (add-eval-verdict-ledger 3.3) ──────────────────
    # Subject = the judge itself (model + prompt version); ruler = the gold set
    # this calibration ran against, with its canonical digest. Editing either
    # the judge's prompt or the gold set changes an identity that the ledger
    # records, so yesterday's calibration cannot silently vouch for today's.
    #
    # ``outcome`` is THREE-state and deliberately NOT the same thing as
    # ``all_pass``: gates can pass on too little evidence (n below
    # CALIBRATION_MIN_SAMPLES) and that is "inconclusive", not "pass". The
    # legacy ``all_pass`` column keeps its exact meaning so the existing
    # read paths (is_calibrated, drift_check) are untouched.
    if not all_pass:
        calibration_outcome = "fail"
    elif n < CALIBRATION_MIN_SAMPLES:
        calibration_outcome = "inconclusive"
    else:
        calibration_outcome = "pass"
    judge_subject = verdicts.judge_subject_key(judge_model, prompt_version)
    gold_ruler = verdicts.gold_set_ruler(validated, key=f"gold:{judge_subject}")

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
                f"agree_rate={agree_rate:.4f} (diagnostic), "
                f"balanced_accuracy={ba_fragment} "
                f"(gate min {CALIBRATION_MIN_AGREE:.2f}), "
                f"monotonic={'yes' if mono_ok else 'no'}; "
                f"{provenance}; {mono_detail}"
            ),
            "judge_model": judge_model,
            "criteria_results": criteria_results,
        },
        task_desc=(
            f"prompt_version={prompt_version}"
            + (f" candidate={candidate}" if candidate else "")
            + (f" samples={samples}" if samples > 1 else "")
        ),
        db_path=db_path,
        channel="meta",
        unit_kind="judge",
        subject_kind=verdicts.JUDGE_SUBJECT_KIND,
        subject_key=judge_subject,
        subject_version=gold_ruler["digest"],
        ruler_kind=gold_ruler["kind"],
        ruler_key=gold_ruler["key"],
        ruler_digest=gold_ruler["digest"],
        gate=verdicts.CALIBRATION_GATE,
        outcome=calibration_outcome,
    )

    return {
        "run_id": run_id,
        "rubric": rubric_name,
        "judge_model": judge_model,
        "prompt_version": prompt_version,
        "candidate": candidate,
        "samples": samples,
        "n_calls": n_calls,
        "n": n,
        "agrees": agrees,
        "agree_rate": agree_rate,
        "matrix": matrix,
        "balanced_accuracy": balanced_accuracy,
        "kappa": matrix["kappa"],
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
    read path). Calibrated iff that run's ``all_pass`` is set — balanced
    accuracy at or above ``CALIBRATION_MIN_AGREE`` and monotonic confidence
    buckets — AND it scored at least ``CALIBRATION_MIN_SAMPLES`` paired gold
    records (the record count is parsed from the run's ``summary``, the
    writer's own format).

    Returns ``(ok, reason)``; the reason always names which path applies: no
    calibration run / not enough samples / gates not met (balanced accuracy
    or monotonicity). Runs written before the stratified gate (no
    ``balanced_accuracy=`` summary fragment) fall back to the legacy
    agree-rate wording so old rows stay readable.
    """
    rubric_name = f"judge-calibration:{judge_model}@{prompt_version}"
    row = conn.execute(
        "SELECT id, score, all_pass, summary, outcome FROM eval_runs "
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
    ba_match = _BAL_ACC_FRAGMENT_RE.search(summary)
    n: Optional[int] = int(n_match.group(1)) if n_match else None

    # ── the decision reads the ledger's three-state outcome ─────────────────
    # ``all_pass`` alone cannot express "gates passed on too little evidence",
    # so a run that squeaked past the gates at n=10 used to be reported as
    # calibrated by the pack gate. The verdict ledger records that case as
    # ``inconclusive``; this function and ``verdicts.provisional`` must give the
    # same answer to the same question ("is this judge calibrated?"), so the
    # outcome decides and the ``all_pass`` path below is the legacy fallback for
    # rows written before the ledger existed (their outcome is derived from
    # all_pass, so they reach the same verdict either way).
    ledger_outcome = row["outcome"]
    if ledger_outcome == "inconclusive":
        return False, (
            f"calibration run {row['id']} did not decide: the gates passed but "
            f"on too little evidence (n={n if n is not None else 'unknown'}, "
            f"minimum {CALIBRATION_MIN_SAMPLES} paired gold records)"
        )

    if not bool(row["all_pass"]):
        # Monotonicity is its own gate: report it first when the summary
        # says the buckets failed, so the reason names the actual failing
        # gate instead of a misleading balanced-accuracy number.
        if mono_match is not None and mono_match.group(1) == "no":
            return False, (
                f"calibration run {row['id']} not passed: per-bucket accuracy is "
                f"not monotonic in confidence (monotonic=no)"
            )
        if ba_match is not None:
            if ba_match.group(1) == "none":
                return False, (
                    f"calibration run {row['id']} not passed: balanced "
                    f"accuracy is undefinable on this gold "
                    f"(single-class strata; "
                    f"n={n if n is not None else 'unknown'})"
                )
            if float(ba_match.group(1)) < CALIBRATION_MIN_AGREE:
                return False, (
                    f"calibration run {row['id']} not passed: balanced_accuracy "
                    f"{ba_match.group(1)} is below the required "
                    f"{CALIBRATION_MIN_AGREE:.2f} "
                    f"(n={n if n is not None else 'unknown'})"
                )
        if float(row["score"]) < CALIBRATION_MIN_AGREE:
            return False, (
                f"calibration run {row['id']} not passed (legacy gate): "
                f"agree_rate "
                f"{float(row['score']):.4f} is below the required "
                f"{CALIBRATION_MIN_AGREE:.2f} "
                f"(n={n if n is not None else 'unknown'})"
            )
        return False, (
            f"calibration run {row['id']} not passed: calibration gates not met"
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
    ba_text = (
        f"balanced_accuracy {ba_match.group(1)}"
        if ba_match is not None
        else f"agree_rate {float(row['score']):.4f} (legacy)"
    )
    return True, (
        f"calibration run {row['id']}: {ba_text} "
        f">= {CALIBRATION_MIN_AGREE:.2f}, "
        f"monotonic={mono_match.group(1) if mono_match else 'yes'}, "
        f"n={n} >= {CALIBRATION_MIN_SAMPLES}"
    )
