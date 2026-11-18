#!/usr/bin/env python3
"""Interactive y/n/s CLI for approving bootstrap envelopes into gold.

Walks the envelope sorted by confidence DESC, shows:
  - the model reasoning
  - the human-authored criteria guidance (the PASS/FAIL rule)
  - the model's verdict

Reads one keystroke per item:
  y = approved → review.status=approved, review.reviewer=human
  n = rejected → review.status=rejected
  s = skip     → review.status=pending
  q = quit

Writes back the file in place after each entry so progress is preserved.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import read_jsonl, write_jsonl  # noqa: E402

DEFAULT_INBOX = pathlib.Path("data/finetune/review/inbox/bootstrap")


def _cbreak() -> tuple[int, list]:
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return fd, old


def _restore(fd: int, old: list) -> None:
    import termios
    termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key() -> str:
    ch = sys.stdin.read(1)
    return ch.lower()


def _show(env: dict, idx: int, total: int) -> None:
    q = env["quadruple"]
    r = env["review"]
    print("─" * 78)
    print(f"[{idx+1}/{total}] conf={env['confidence']:.2f} | {env['rubric']['name']} | "
          f"run:{env['clause_id']} | judge={env.get('judge_model','?')} | "
          f"verdict={q['verdict']}")
    print(f"  contract: {env.get('contract_path','?')}")
    print(f"  criterion: {env['rule']['constraint_id']}")
    print()
    print(f"  ▸ HUMAN RULE (legal_base):")
    print(f"    {q['legal_base']['text']}")
    print()
    print(f"  ▸ MODEL REASONING:")
    print(f"    {q['reasoning']['justification']}")
    print()
    print(f"  ▸ MODEL VERDICT: {q['verdict'].upper()}")
    print(f"  ▸ CURRENT REVIEW: status={r['status']}, annotator={r.get('annotator')}")
    print()
    sys.stdout.write("  [y] approve  [n] reject  [s] skip  [q] quit > ")
    sys.stdout.flush()


def _save(path: pathlib.Path, envelopes: list[dict]) -> None:
    write_jsonl(path, envelopes)


def cmd_approve(args: argparse.Namespace) -> int:
    target = pathlib.Path(args.file)
    if not target.exists():
        print(f"no file: {target}")
        return 1

    envelopes = read_jsonl(target)
    # only review the not-yet-decided ones
    pending = [i for i, e in enumerate(envelopes)
               if (e.get("review") or {}).get("status") in ("ai_seeded", "pending")]

    print(f"file: {target}  ({len(pending)} pending / {len(envelopes)} total)")
    print(f"controls: y=approve  n=reject  s=skip  q=quit")
    if not pending:
        print("nothing to review")
        return 0

    fd, old = _cbreak()
    try:
        for n, idx in enumerate(pending):
            env = envelopes[idx]
            _show(env, n, len(pending))
            ch = _read_key()
            print(ch)  # echo
            if ch == "q":
                break
            elif ch == "y":
                env["review"]["status"] = "approved"
                env["review"]["reviewer"] = "human"
                env["review"]["annotator"] = args.annotator
                env["review"]["notes"] = env["review"].get("notes", "")
            elif ch == "n":
                env["review"]["status"] = "rejected"
                env["review"]["annotator"] = args.annotator
            else:  # s or anything else = skip
                env["review"]["status"] = "pending"
            _save(target, envelopes)
    finally:
        _restore(fd, old)

    approved = sum(1 for e in envelopes if (e.get("review") or {}).get("status") == "approved")
    rejected = sum(1 for e in envelopes if (e.get("review") or {}).get("status") == "rejected")
    pending_n = sum(1 for e in envelopes if (e.get("review") or {}).get("status") in ("ai_seeded", "pending"))
    print()
    print(f"summary: approved={approved}  rejected={rejected}  pending={pending_n}")
    print(f"next: python scripts/finetune/prepare_review_batches.py promote "
          f"--from-dir data/finetune/review/done --out data/finetune/judge-c/judge_c_gold.bootstrap.jsonl")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    target_dir = pathlib.Path(args.dir)
    if not target_dir.is_dir():
        print(f"no dir: {target_dir}")
        return 1
    total = approved = rejected = pending = 0
    for f in sorted(target_dir.glob("*.jsonl")):
        rows = read_jsonl(f)
        a = sum(1 for e in rows if (e.get("review") or {}).get("status") == "approved")
        r = sum(1 for e in rows if (e.get("review") or {}).get("status") == "rejected")
        p = sum(1 for e in rows if (e.get("review") or {}).get("status") in ("ai_seeded", "pending"))
        total += len(rows)
        approved += a
        rejected += r
        pending += p
        print(f"  {f.name:<60} total={len(rows):>4}  ok={a:>4}  no={r:>4}  pending={p:>4}")
    print("─" * 100)
    print(f"  {'TOTAL':<60} total={total:>4}  ok={approved:>4}  no={rejected:>4}  pending={pending:>4}")
    return 0


def cmd_auto(args: argparse.Namespace) -> int:
    """Bulk-approve envelopes with confidence >= threshold.

    Sets ``review.status=approved``, ``review.reviewer=ai_reviewer`` (so
    promote yields gold with reviewer=ai_reviewer, not human), and
    ``review.annotated_by=ai_auto_approved``. The human can later flip
    specific envelopes to reviewer=human by editing the file.
    """
    target_dir = pathlib.Path(args.dir)
    threshold = args.threshold
    if not target_dir.is_dir():
        print(f"no dir: {target_dir}")
        return 1

    n_files = approved = skipped = 0
    for f in sorted(target_dir.glob("*.jsonl")):
        envelopes = read_jsonl(f)
        n_files += 1
        changed = False
        for env in envelopes:
            r = env.get("review") or {}
            if r.get("status") in ("approved", "rejected"):
                continue
            conf = env.get("confidence", 0.0)
            if conf >= threshold:
                env["review"] = {
                    **r,
                    "status": "approved",
                    "reviewer": "ai_reviewer",
                    "annotator": "ai_auto_approve",
                    "notes": f"auto-approved (conf={conf:.2f} >= {threshold})",
                }
                approved += 1
                changed = True
            else:
                skipped += 1
        if changed:
            _save(f, envelopes)
    print(f"auto-approved {approved} envelopes (>= {threshold})")
    print(f"left for human review: {skipped}")
    print(f"files touched: {n_files}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ap = sub.add_parser("approve", help="interactively approve one batch")
    p_ap.add_argument("file", help="JSONL file to walk")
    p_ap.add_argument("--annotator", default="human_anon", help="annotator name to stamp")
    p_ap.set_defaults(func=cmd_approve)

    p_sum = sub.add_parser("summary", help="show review progress across all bootstrap batches")
    p_sum.add_argument("--dir", default=str(DEFAULT_INBOX), help="directory of bootstrap batches")
    p_sum.set_defaults(func=cmd_summary)

    p_auto = sub.add_parser("auto", help="bulk-approve envelopes with confidence >= threshold")
    p_auto.add_argument("--dir", default=str(DEFAULT_INBOX), help="directory of bootstrap batches")
    p_auto.add_argument("--threshold", type=float, default=0.6, help="confidence floor (default 0.6)")
    p_auto.set_defaults(func=cmd_auto)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
