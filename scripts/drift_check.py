#!/usr/bin/env python3
"""Quarterly judge-drift meta-eval: compare the two latest stored calibrations.

Scheduler-facing job for change add-knowledge-bench-platform, task 6.3
("meta-eval 常态化: 季度漂移检测入调度"). The same judge, on the same gold
set, is calibrated once a quarter by ``scripts/calibrate_judge_live.py``; this
script *compares* the two newest generations of that meta run and raises an
alarm when the current quarter has measurably degraded against the previous
baseline. It performs **zero LLM calls** — it is pure deterministic arithmetic
over data already in ``eval_runs`` (or over two calibration-result JSON files),
so it is safe to run from a CronJob without judge credentials beyond the DB.

Comparison inputs (two mutually exclusive modes):

- DB mode (default): the two most recent ``eval_runs`` rows with
  ``channel='meta' AND unit_kind='judge'`` and
  ``rubric_name='judge-calibration:<judge_model>@<prompt_version>'`` — the
  contract written by :func:`src.bench.calibration.run_calibration`. The
  newest row is "this quarter", the one before it is the baseline.
- File-diff mode (``--baseline F --current F``): two calibration-result JSON
  files in the shape ``run_calibration`` returns (``agree_rate``,
  ``monotonic``, ``n``, optionally ``judge_model`` / ``prompt_version`` /
  ``run_id``).

Drift is declared when either degradation signal fires:

1. agree-rate drop: ``baseline.agree_rate - current.agree_rate`` is strictly
   greater than the threshold (default ``0.05``, overridable via env
   ``DRIFT_THRESHOLD`` or ``--threshold``; precedence CLI > env > default);
2. monotonicity flip: the baseline's per-bucket accuracy was monotonic in
   confidence (``monotonic=yes``) and the current run's is not
   (``monotonic=no``) — parsed from the run summary's machine-readable
   fragment, the calibration module's own format.

With fewer than two stored calibration runs (or summaries whose machine-
readable fragments cannot be parsed) the report is honestly
``status="not_comparable"``: nothing is fabricated and **no eval_runs row is
written** — a non-comparison leaves no comparison record.

When comparable, one meta bookkeeping row is stored via
:func:`src.eval.store.store_result`:

- ``channel`` = ``'meta'``, ``unit_kind`` = ``'drift'`` (never pollutes the
  calibration-run query above)
- ``rubric_name`` = ``drift-check:<judge_model>@<prompt_version>``
- ``score`` = the current run's agree rate, ``max_score`` = 1.0
- ``all_pass`` = 1 iff no drift was detected (the run-level alarm)
- three ``eval_criteria_results`` diagnostic rows: ``compare:agree_rate_drop``
  (verdict fail iff the drop breaches the threshold), ``compare:monotonicity``
  (fail iff a yes->no flip), ``compare:sample_size`` (informational, always
  pass)

Stdout is exactly one structured JSON report (also carrying ``drift_run_id``
when stored). Exit codes: ``0`` ok / not_comparable (nothing to alarm about),
``1`` drift detected (alarm — a CronJob run shows as Failed), ``2`` bad input
(missing flags, unparseable threshold, mismatched JSON files).

Usage::

    python3 scripts/drift_check.py --judge-model EVAL_MODEL --prompt-version v2-structure
    python3 scripts/drift_check.py --baseline /tmp/cal_prev.json --current /tmp/cal_now.json

Env: ``database_url`` (PostgreSQL DSN) for DB mode and for storing the drift
record; ``DRIFT_THRESHOLD`` optional.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bench.calibration import CALIBRATION_MIN_AGREE  # noqa: E402
from src.eval.db import connect  # noqa: E402
from src.eval.store import store_result  # noqa: E402
from src.settings import DEFAULT_DB, ConfigError  # noqa: E402

# Agree-rate drop that counts as drift (strictly greater than). Overridable
# per run with --threshold or the DRIFT_THRESHOLD environment variable.
DEFAULT_DRIFT_THRESHOLD = 0.05
THRESHOLD_ENV = "DRIFT_THRESHOLD"
# Floating-point guard so a drop of *exactly* the threshold is not flagged as
# "greater than" it (e.g. 0.9 - 0.85 == 0.05000000000000004 in IEEE-754).
_FLOAT_EPS = 1e-9
# Rubric-name prefixes shared with src.bench.calibration's stored-row
# contract (writer: run_calibration; drift rows are ours only).
CALIBRATION_RUBRIC_PREFIX = "judge-calibration:"
DRIFT_RUBRIC_PREFIX = "drift-check:"

# Machine-readable summary fragments written by run_calibration and parsed
# back here (same contract is_calibrated parses).
_MONO_FRAGMENT_RE = re.compile(r"monotonic=(yes|no)")
_N_FRAGMENT_RE = re.compile(r"(?:^|[\s;])n=(\d+)")


def calibration_rubric_name(judge_model: str, prompt_version: str) -> str:
    return f"{CALIBRATION_RUBRIC_PREFIX}{judge_model}@{prompt_version}"


def drift_rubric_name(judge_model: str, prompt_version: str) -> str:
    return f"{DRIFT_RUBRIC_PREFIX}{judge_model}@{prompt_version}"


def resolve_threshold(cli_value: Optional[float] = None) -> float:
    """CLI flag > DRIFT_THRESHOLD env > DEFAULT_DRIFT_THRESHOLD; validated.

    Raises ValueError naming the offending value when the env override is not
    a number in [0, 1] — a scheduler with a typo'd threshold must fail loudly
    rather than silently drift-gate on the wrong bar.
    """
    def _validated(value: Any, origin: str) -> float:
        try:
            t = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"{origin} threshold {value!r} is not a number"
            ) from None
        if not 0.0 <= t <= 1.0:
            raise ValueError(
                f"{origin} threshold {t} is outside [0, 1] "
                f"(the default is {DEFAULT_DRIFT_THRESHOLD})"
            )
        return t

    if cli_value is not None:
        return _validated(cli_value, "--threshold")
    env = os.environ.get(THRESHOLD_ENV, "").strip()
    if env:
        return _validated(env, f"env {THRESHOLD_ENV}")
    return DEFAULT_DRIFT_THRESHOLD


def _parse_summary_fragments(summary: Optional[str]) -> tuple[Optional[bool], Optional[int]]:
    """(monotonic flag, n) from a calibration run's summary; None when absent."""
    text = summary or ""
    mono = _MONO_FRAGMENT_RE.search(text)
    n = _N_FRAGMENT_RE.search(text)
    return (
        (mono.group(1) == "yes") if mono else None,
        int(n.group(1)) if n else None,
    )


def _run_to_calibration(row: dict) -> dict:
    """Normalize one eval_runs calibration row into a comparable dict.

    ``agree_rate`` comes from the ``score`` column (run_calibration stores
    exactly that); ``monotonic`` / ``n`` are parsed from the summary fragments
    and stay ``None`` when unparseable, which compare_calibrations reports as
    not_comparable instead of guessing.
    """
    monotonic, n = _parse_summary_fragments(row["summary"])
    return {
        "source": "eval_runs",
        "run_id": row["id"],
        "judge_model": row["judge_model"],
        "agree_rate": float(row["score"]),
        "monotonic": monotonic,
        "n": n,
    }


def fetch_calibration_runs(
    conn: Any, *, judge_model: str, prompt_version: str, limit: int = 2
) -> list[dict]:
    """The newest ``limit`` judge-calibration meta runs, most recent first."""
    rows = conn.execute(
        "SELECT id, score, all_pass, summary, judge_model "
        "FROM eval_runs "
        "WHERE rubric_name = %s AND judge_model = %s "
        "  AND channel = 'meta' AND unit_kind = 'judge' "
        "ORDER BY id DESC LIMIT %s",
        (calibration_rubric_name(judge_model, prompt_version), judge_model, int(limit)),
    ).fetchall()
    return [_run_to_calibration(r) for r in rows]


def load_calibration_result(path: str | Path) -> dict:
    """Load one calibration-result JSON file (run_calibration's return shape)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a calibration-result JSON object")
    agree = data.get("agree_rate")
    mono = data.get("monotonic")
    return {
        "source": str(path),
        "run_id": data.get("run_id"),
        "judge_model": data.get("judge_model"),
        "prompt_version": data.get("prompt_version"),
        "agree_rate": None if agree is None else float(agree),
        "monotonic": None if mono is None else bool(mono),
        "n": data.get("n"),
    }


def compare_calibrations(
    baseline: dict, current: dict, threshold: float = DEFAULT_DRIFT_THRESHOLD
) -> dict:
    """Pure drift comparison of two normalized calibration dicts.

    Returns ``{"status": "ok" | "drift" | "not_comparable", ...}``; with
    ``status != "not_comparable"`` also ``agree_rate_drop`` (baseline minus
    current, positive == degradation), ``agree_rate_drift`` and
    ``monotonicity_flip`` booleans plus the two input dicts echoed under
    ``baseline`` / ``current``. No DB, no LLM, no clock: deterministic.
    """
    problems = []
    for label, rec in (("baseline", baseline), ("current", current)):
        if rec is None or rec.get("agree_rate") is None:
            problems.append(f"{label} agree_rate is missing/unparseable")
        if rec is None or rec.get("monotonic") is None:
            problems.append(f"{label} monotonic flag is missing/unparseable")
    if problems:
        return {
            "status": "not_comparable",
            "reason": "cannot compare: " + "; ".join(problems),
        }

    b_rate = float(baseline["agree_rate"])
    c_rate = float(current["agree_rate"])
    b_mono = bool(baseline["monotonic"])
    c_mono = bool(current["monotonic"])
    drop = b_rate - c_rate
    agree_drift = drop > threshold + _FLOAT_EPS
    flip = b_mono and not c_mono
    return {
        "status": "drift" if (agree_drift or flip) else "ok",
        "agree_rate_drop": drop,
        "threshold": threshold,
        "agree_rate_drift": agree_drift,
        "monotonicity_flip": flip,
        "baseline": baseline,
        "current": current,
    }


def _fmt(value: Any) -> str:
    return "unknown" if value is None else str(value)


def build_drift_criteria(report: dict) -> list[dict]:
    """The three diagnostic criteria rows mirrored into the stored drift run."""
    b, c = report["baseline"], report["current"]
    drop = report["agree_rate_drop"]
    thr = report["threshold"]
    return [
        {
            "id": "compare:agree_rate_drop",
            "title": "agree_rate drop vs baseline",
            "verdict": "fail" if report["agree_rate_drift"] else "pass",
            "reasoning": (
                f"baseline {float(b['agree_rate']):.4f} -> current "
                f"{float(c['agree_rate']):.4f} "
                f"(drop {drop:.4f} vs threshold {thr:g}): "
                + ("drift" if report["agree_rate_drift"] else "within threshold")
            ),
        },
        {
            "id": "compare:monotonicity",
            "title": "per-bucket monotonicity flip (yes -> no)",
            "verdict": "fail" if report["monotonicity_flip"] else "pass",
            "reasoning": (
                f"baseline monotonic={'yes' if b['monotonic'] else 'no'} -> "
                f"current monotonic={'yes' if c['monotonic'] else 'no'}: "
                + ("flip detected" if report["monotonicity_flip"] else "no flip")
            ),
        },
        {
            "id": "compare:sample_size",
            "title": "paired gold record counts (informational)",
            "verdict": "pass",
            "reasoning": (
                f"baseline n={_fmt(b.get('n'))} (run {_fmt(b.get('run_id'))}), "
                f"current n={_fmt(c.get('n'))} (run {_fmt(c.get('run_id'))})"
            ),
        },
    ]


def store_drift_run(
    *,
    judge_model: str,
    prompt_version: str,
    report: dict,
    db_path: Any = DEFAULT_DB,
) -> int:
    """Persist the drift-check as one meta/drift eval run; returns its run id.

    ``all_pass`` = 1 iff no drift (the alarm bit); ``score`` = the current
    quarter's agree rate.
    """
    criteria = build_drift_criteria(report)
    b, c = report["baseline"], report["current"]
    summary = (
        f"drift-check: status={report['status']}, "
        f"judge={judge_model}@{prompt_version}, "
        f"baseline_run={_fmt(b.get('run_id'))} "
        f"(agree_rate={float(b['agree_rate']):.4f}, "
        f"monotonic={'yes' if b['monotonic'] else 'no'}, n={_fmt(b.get('n'))}), "
        f"current_run={_fmt(c.get('run_id'))} "
        f"(agree_rate={float(c['agree_rate']):.4f}, "
        f"monotonic={'yes' if c['monotonic'] else 'no'}, n={_fmt(c.get('n'))}), "
        f"agree_rate_drop={report['agree_rate_drop']:.4f} "
        f"(threshold {report['threshold']:g}), "
        f"monotonicity_flip={'yes' if report['monotonicity_flip'] else 'no'}, "
        f"min_agree_bar={CALIBRATION_MIN_AGREE:g}"
    )
    return store_result(
        {
            "rubric": drift_rubric_name(judge_model, prompt_version),
            "score": float(c["agree_rate"]),
            "max_score": 1.0,
            "all_pass": report["status"] == "ok",
            "n_criteria": len(criteria),
            "n_passed": sum(1 for x in criteria if x["verdict"] == "pass"),
            "summary": summary,
            "judge_model": judge_model,
            "criteria_results": criteria,
        },
        task_desc=f"prompt_version={prompt_version}",
        db_path=db_path,
        channel="meta",
        unit_kind="drift",
    )


def _attach_identity(report: dict, judge_model: str, prompt_version: str, threshold: float) -> dict:
    report = dict(report)
    report["judge_model"] = judge_model
    report["prompt_version"] = prompt_version
    report["threshold"] = threshold
    return report


def run_drift_check(
    conn: Any,
    *,
    judge_model: str,
    prompt_version: str,
    threshold: Optional[float] = None,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """DB-mode drift check: fetch the two newest calibrations, compare, store.

    Returns the structured report. ``not_comparable`` paths carry
    ``drift_run_id=None`` and write no eval_runs row (honest non-comparison).
    """
    if not isinstance(judge_model, str) or not judge_model.strip():
        raise ValueError("judge_model must be a non-empty string")
    if not isinstance(prompt_version, str) or not prompt_version.strip():
        raise ValueError("prompt_version must be a non-empty string")
    thr = resolve_threshold(threshold)
    runs = fetch_calibration_runs(conn, judge_model=judge_model, prompt_version=prompt_version)
    if len(runs) < 2:
        report = _attach_identity(
            {
                "status": "not_comparable",
                "reason": (
                    f"no calibration runs stored for judge '{judge_model}' @ "
                    f"prompt version '{prompt_version}'; nothing to compare"
                    if not runs
                    else f"only 1 calibration run stored for judge '{judge_model}' @ "
                    f"prompt version '{prompt_version}'; need 2 generations "
                    f"(this quarter + previous baseline)"
                ),
                "runs_found": len(runs),
                "drift_run_id": None,
            },
            judge_model,
            prompt_version,
            thr,
        )
        return report
    current, baseline = runs[0], runs[1]
    report = _attach_identity(
        compare_calibrations(baseline, current, thr),
        judge_model,
        prompt_version,
        thr,
    )
    if report["status"] == "not_comparable":
        report["drift_run_id"] = None
        return report
    report["drift_run_id"] = store_drift_run(
        judge_model=judge_model,
        prompt_version=prompt_version,
        report=report,
        db_path=db_path if db_path is not None else conn,
    )
    return report


def resolve_file_identity(
    baseline: dict,
    current: dict,
    *,
    judge_model: Optional[str],
    prompt_version: Optional[str],
) -> tuple[str, str]:
    """judge/version precedence: CLI flags > baseline JSON; cross-checked."""
    jm = (judge_model or baseline.get("judge_model") or "").strip()
    pv = (prompt_version or baseline.get("prompt_version") or "").strip()
    if not jm:
        raise ValueError(
            "judge_model is unknown: pass --judge-model or put it in the JSON files"
        )
    if not pv:
        raise ValueError(
            "prompt_version is unknown: pass --prompt-version or put it in the JSON files"
        )
    for label, rec in (("baseline", baseline), ("current", current)):
        if rec.get("judge_model") and str(rec["judge_model"]).strip() != jm:
            raise ValueError(
                f"{label} JSON judge_model {rec['judge_model']!r} does not match "
                f"the compared judge {jm!r}"
            )
        if rec.get("prompt_version") and str(rec["prompt_version"]).strip() != pv:
            raise ValueError(
                f"{label} JSON prompt_version {rec['prompt_version']!r} does not "
                f"match the compared version {pv!r}"
            )
    return jm, pv


def run_drift_check_files(
    conn: Any,
    *,
    baseline_path: str | Path,
    current_path: str | Path,
    judge_model: Optional[str] = None,
    prompt_version: Optional[str] = None,
    threshold: Optional[float] = None,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """File-diff mode: compare two given calibration-result JSONs, then store."""
    thr = resolve_threshold(threshold)
    baseline = load_calibration_result(baseline_path)
    current = load_calibration_result(current_path)
    jm, pv = resolve_file_identity(
        baseline, current, judge_model=judge_model, prompt_version=prompt_version
    )
    report = _attach_identity(compare_calibrations(baseline, current, thr), jm, pv, thr)
    if report["status"] == "not_comparable":
        report["drift_run_id"] = None
        return report
    report["drift_run_id"] = store_drift_run(
        judge_model=jm,
        prompt_version=pv,
        report=report,
        db_path=db_path if db_path is not None else conn,
    )
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="drift_check.py",
        description=(
            "Quarterly judge-drift meta-eval: compare the two latest stored "
            "judge calibrations (DB mode) or two given calibration-result JSON "
            "files (file-diff mode); exit 1 on drift."
        ),
    )
    ap.add_argument(
        "--judge-model",
        dest="judge_model",
        help="judge the calibration runs are keyed by (required in DB mode)",
    )
    ap.add_argument(
        "--prompt-version",
        dest="prompt_version",
        help="judge prompt version the runs are keyed by (required in DB mode)",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=(
            f"agree-rate drop (strictly greater) counted as drift; default "
            f"{DEFAULT_DRIFT_THRESHOLD}, env {THRESHOLD_ENV} overrides the "
            "default, an explicit flag overrides both"
        ),
    )
    ap.add_argument(
        "--baseline",
        help="path to a calibration-result JSON of the previous baseline (file-diff mode)",
    )
    ap.add_argument(
        "--current",
        help="path to a calibration-result JSON of this quarter (file-diff mode)",
    )
    args = ap.parse_args(argv)

    try:
        thr = resolve_threshold(args.threshold)
        if args.baseline or args.current:
            if not (args.baseline and args.current):
                raise ValueError("file-diff mode needs BOTH --baseline and --current")
            conn = connect()
            report = run_drift_check_files(
                conn,
                baseline_path=args.baseline,
                current_path=args.current,
                judge_model=args.judge_model,
                prompt_version=args.prompt_version,
                threshold=thr,
                db_path=conn,
            )
        else:
            if not args.judge_model or not args.prompt_version:
                raise ValueError(
                    "DB mode needs --judge-model and --prompt-version "
                    "(or use file-diff mode with --baseline and --current)"
                )
            conn = connect()
            report = run_drift_check(
                conn,
                judge_model=args.judge_model,
                prompt_version=args.prompt_version,
                threshold=thr,
                db_path=conn,
            )
    except (ValueError, ConfigError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "drift" else 0


if __name__ == "__main__":
    sys.exit(main())
