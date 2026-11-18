#!/usr/bin/env python3
"""Classify rows written before ``assignee_kind`` existed.

Why this exists: the column arrives with ``DEFAULT 'human'``, so every pre-change
row *claims* to be a human assignment. That claim is false for any row whose
``assignee`` reads ``agent:<role>@<domain>`` or ``fleet:<ref>`` — and a false
"human" is the dangerous direction: the console would offer it to a person who
cannot act on it, while the kernel role that owns the gap never sees it.

**Nothing is inferred from free text.** Only the two shapes the platform itself
mints are classified:

    agent:<role>@<domain>   -> kernel-role / <role>
    fleet:<fleet_ref>/...   -> fleet / <fleet_ref>

Everything else stays ``human`` — including ``alice@example.com`` — because a
human display name is genuinely a person, and guessing otherwise would move work
away from someone who is actually doing it.

The display column ``assignee`` is never rewritten: it is what a person reads,
and this script's job is authorization, not presentation.

Run:
    uv run python scripts/backfill_assignee_kind.py --dry-run
    uv run python scripts/backfill_assignee_kind.py --apply

Exit codes: 0 ok, 2 unusable database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _connect():
    from src.eval.db import connect

    return connect()


def classify(assignee: str, *, roles=None) -> tuple[str, str | None] | None:
    """``(kind, ref)`` for a minted shape, ``None`` when nothing can be inferred.

    ``roles`` is the kernel role vocabulary; an ``agent:`` name whose role is not
    in it resolves to ``kernel-role`` anyway — the gap route, not this script, is
    the authority on which role owns what, and mislabelling it ``human`` would be
    worse than a role the console can show as unknown.
    """
    text = (assignee or "").strip()
    if text.startswith("agent:"):
        rest = text[len("agent:"):]
        role, _, domain = rest.partition("@")
        role = role.strip()
        if role and domain.strip():
            return ("kernel-role", role)
        return None
    if text.startswith("fleet:"):
        rest = text[len("fleet:"):]
        fleet_ref = rest.split("/", 1)[0].strip()
        if fleet_ref:
            return ("fleet", fleet_ref)
        return None
    return None


def _rows(conn) -> list[dict]:
    cur = conn.execute(
        "SELECT id, assignee, assignee_kind, assignee_ref, target_kind, target_key "
        "FROM authoring_tasks ORDER BY id"
    )
    return [dict(r) for r in cur.fetchall()]


def run(conn, *, apply: bool) -> int:
    rows = _rows(conn)
    plans: list[tuple[dict, str, str | None]] = []
    untouched = 0
    for row in rows:
        if row["assignee_kind"] != "human" or row["assignee_ref"] is not None:
            untouched += 1  # already typed; never overwrite a deliberate value
            continue
        decision = classify(row["assignee"])
        if decision is None:
            untouched += 1
            continue
        kind, ref = decision
        if kind == "human":
            untouched += 1
            continue
        plans.append((row, kind, ref))

    counts: dict[str, int] = {}
    for _row, kind, _ref in plans:
        counts[kind] = counts.get(kind, 0) + 1

    print(f"tasks: {len(rows)}  rows to classify: {len(plans)}  left alone: {untouched}")
    for kind in sorted(counts):
        print(f"  -> {kind:<12} {counts[kind]}")
    for row, kind, ref in plans:
        print(f"  #{row['id']:<6} {row['assignee']:<40} -> {kind} / {ref}")

    if not plans:
        print("nothing to do")
        return 0
    if not apply:
        print("\n(dry run — nothing written; re-run with --apply)")
        return 0

    for row, kind, ref in plans:
        conn.execute(
            "UPDATE authoring_tasks SET assignee_kind = %s, assignee_ref = %s, "
            "updated_at = now() WHERE id = %s",
            (kind, ref, row["id"]),
        )
    conn.commit()
    print(f"\nupdated {len(plans)} row(s); display name untouched")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="explicit no-op (the default)")
    args = ap.parse_args(argv)

    try:
        conn = _connect()
    except Exception as exc:  # noqa: BLE001 - unusable DB must not look like success
        print(f"cannot reach the database: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    try:
        try:
            return run(conn, apply=args.apply)
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ in ("UndefinedTable", "UndefinedColumn"):
                # 两种都是「还没到这一步」，但原因不同，得分开说：没有表＝库是空
                # 的；没有列＝库停在变更前——而那正是本脚本要回填的那批行所在的
                # 库，所以先把列建出来（启动一次）再回来。
                print(
                    f"这个库还没有类型化指派人所需的表/列（{type(exc).__name__}: {exc}）。\n"
                    "  先跑一次启动步骤（ensure_schema）把 assignee_kind / assignee_ref "
                    "建出来，再回来回填。",
                    file=sys.stderr,
                )
                return 2
            raise
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
