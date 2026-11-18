#!/usr/bin/env python3
"""给舰队派一张真实工单 —— §6.4 同片对跑的起点（add-fleet-execution-loop）。

为什么需要脚本：生产上派单的**唯一**入口是控制台（Logto 会话），机器面没有派单口
——这是设计，舰队不该给自己派活。所以「派单」这一步本来是人做的；本脚本只是把那个
人的动作记成可复现的一行，供验收与演示使用。

它**不新增任何权限面**：走的是控制台同一个库函数 `authoring_create_task`，`fleet`
档指派的校验也在那里（`resolve_fleet` 要求域内有一条活的 fleet 登记），所以
「派给一个没登记的舰队」在这里同样会被拒——脚本不会绕过它。

用法：
  PYTHONPATH=. python scripts/seed_fleet_work_order.py \
      --fleet-ref fleet_1794335712751_wfa3ww --domain legal \
      --title "…" --detail "…" [--target-kind company --target-key …] [--apply]

默认 dry-run：只打印将要写入的行，不写库。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CREATED_BY = "seed:fleet-loop-acceptance"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--fleet-ref", required=True, help="bare fleet id, e.g. fleet_1794335712751_wfa3ww")
    ap.add_argument("--domain", required=True, help="domain key the task belongs to")
    ap.add_argument("--title", required=True)
    ap.add_argument("--detail", default="")
    ap.add_argument("--target-kind", default=None, help="what the work is *about* (company/concept/…)")
    ap.add_argument("--target-key", default=None)
    ap.add_argument("--assignee-label", default=None, help="human-readable label (default: the fleet ref)")
    ap.add_argument("--apply", action="store_true", help="actually write (default is a dry run)")
    args = ap.parse_args(argv)

    try:
        # `connect()` with no argument returns the PROCESS-WIDE cached connection
        # wrapped in `_BorrowedConn`, whose `close()` is a no-op. Inside a test
        # process that means the second call reuses a connection to a database
        # that may already have been dropped — writes then land somewhere other
        # than the `database_url` this script was told to use (found the hard
        # way: 0 rows in the target DB, "database is being accessed by other
        # users" at teardown). An operator script wants its own connection:
        # `open_fresh_conn()` is the documented entry for exactly that.
        from src.eval.db import open_fresh_conn
    except Exception as exc:  # noqa: BLE001
        print(f"cannot import the app: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    from src.bench import authoring, distribution, workspaces

    conn = open_fresh_conn()
    try:
        domain = workspaces.get_domain(conn, domain_key=args.domain)
        if domain is None:
            print(f"refused: 域 {args.domain!r} 不存在", file=sys.stderr)
            return 1

        # 先按「舰队档」问一次判定：既验证登记存在，也把「为什么不能派」说清。
        consumer, verdict = distribution.resolve_fleet(
            conn, fleet_ref=args.fleet_ref.strip(), domain_key=args.domain
        )
        label = args.assignee_label or args.fleet_ref.strip()
        print(f"domain    : {args.domain} (id={domain['id']})")
        print(f"fleet_ref : {args.fleet_ref.strip()} → verdict={verdict}"
              + (f" (登记 {consumer['name']!r})" if consumer else ""))
        print(f"title     : {args.title}")
        print(f"target    : {args.target_kind or '-'} / {args.target_key or '-'}")
        if verdict != "ok":
            print(
                "refused: 该 fleet_ref 不是本域可用的舰队登记；先去登记（register_fleet.py）。",
                file=sys.stderr,
            )
            return 1

        if not args.apply:
            print("\n(would create ONE pending task assigned to that fleet; dry run — "
                  "re-run with --apply)")
            return 0

        task = authoring.authoring_create_task(
            conn,
            domain_id=domain["id"],
            assignee=label,
            title=args.title,
            detail=(args.detail or None),
            target_kind=args.target_kind,
            target_key=args.target_key,
            created_by=CREATED_BY,
            assignee_kind="fleet",
            assignee_ref=args.fleet_ref.strip(),
        )
        print(f"\ncreated task id={task['id']} status={task['status']} "
              f"assignee_kind={task['assignee_kind']} assignee_ref={task['assignee_ref']}")
        return 0
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
