#!/usr/bin/env python3
"""Batch driver: run self_iterate.py over many contract types sequentially.

Usage:
    python scripts/self_iterate_batch.py <type1> <type2> ... [--max-rounds 3]

Writes per-type logs to output/self_iterate/<type>_run.log and a summary
output/self_iterate/batch_summary.json at the end.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "self_iterate"

JUDGES = ["openai/kimi-k3", "openai/glm-5.2", "openai/qwen-3.7-plus"]

DB_FATAL_MARKERS = ("connection refused", "OperationalError", "could not receive data")


def _wait_for_db(timeout_s: int = 600) -> bool:
    """Block until localhost:15432 accepts connections (port-forward may drop)."""
    import socket
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with socket.create_connection(("localhost", 15432), timeout=3):
                return True
        except OSError:
            time.sleep(5)
    return False


def _run_one(ct: str, max_rounds: int, log: Path) -> tuple[int, str]:
    """Run one type; return (rc, log_text). Caller decides on retry."""
    with open(log, "w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [
                sys.executable, "-u", str(ROOT / "scripts" / "self_iterate.py"),
                ct, "--max-rounds", str(max_rounds),
                "--judges", *JUDGES,
            ],
            cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
        )
    return proc.returncode, log.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("types", nargs="+")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--summary", default="batch_summary.json",
                    help="summary filename under output/self_iterate/ "
                         "(use distinct names for parallel drivers)")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    summary_path = OUT / args.summary
    summary = []
    for i, ct in enumerate(args.types, 1):
        log = OUT / f"{ct}_run.log"
        print(f"\n##### [{i}/{len(args.types)}] {ct} — log: {log}", flush=True)
        t0 = time.time()

        if not _wait_for_db():
            print(f"##### {ct}: DB unreachable after 10min, skipping", flush=True)
            summary.append({"type": ct, "rc": -1, "seconds": 0, "db_down": True})
            summary_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            continue

        rc, log_text = _run_one(ct, args.max_rounds, log)
        # Retry once on infra failure (port-forward dropped mid-run), after
        # waiting for the DB to come back.
        if rc != 0 and any(m in log_text for m in DB_FATAL_MARKERS):
            print(f"##### {ct}: DB failure detected, waiting + retrying once", flush=True)
            if _wait_for_db():
                rc, log_text = _run_one(ct, args.max_rounds, log)

        elapsed = round(time.time() - t0, 1)
        report_path = OUT / f"{ct}_report.json"
        rec = {"type": ct, "rc": rc, "seconds": elapsed}
        if report_path.exists():
            rep = json.loads(report_path.read_text(encoding="utf-8"))
            rec["all_pass"] = rep.get("all_pass")
            rec["rounds"] = len(rep.get("rounds", []))
            if rep.get("rounds"):
                last = rep["rounds"][-1]
                rec["last_score"] = f"{last.get('n_passed')}/{last.get('n_total')}"
        print(f"##### {ct} done rc={rc} {elapsed}s "
              f"all_pass={rec.get('all_pass')} score={rec.get('last_score')}", flush=True)
        summary.append(rec)
        # persist incrementally so a crash keeps prior results
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    n_pass = sum(1 for r in summary if r.get("all_pass"))
    print(f"\n===== BATCH DONE: {n_pass}/{len(summary)} all-pass =====", flush=True)
    for r in summary:
        print(f"  {r['type']:22s} pass={r.get('all_pass')} score={r.get('last_score')} "
              f"rounds={r.get('rounds')} {r['seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
