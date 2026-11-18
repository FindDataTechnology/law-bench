"""登记一个智能体身份：域成员 + 一把不能当管理员的凭据。

    python3 scripts/register_agent.py --role concept --domain legal --dry-run
    python3 scripts/register_agent.py --role concept --domain legal
    python3 scripts/register_agent.py --role concept --domain legal --revoke

为什么要有这个脚本：智能体身份不是"起个名字"，它要**同时**是两样东西——

1. `domain_members` 里 `role=expert` 的普通成员（域内写权限的真实来源）；
2. 一把 `api_keys`（`X-API-Key` 通道的身份就是这行的 `user_id`）。

两处都不写，闸门就会走偏：只有 key 没成员关系 → 域闸 403；只有成员关系没 key →
机器拿不到内容权。所以登记是一件事，不是两件。

**凭据只打印一次**，不落库、不落仓、不写日志。`--revoke` 只撤 key，保留成员关系
（撤成员要显式做，因为那会丢掉审计线索）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bench import agent_ids, workspaces  # noqa: E402
from src.web.auth import apikey  # noqa: E402

#: 智能体能拿的默认 scope：读内容 + 写内容（提案/取用），不含任何平台级权限。
DEFAULT_SCOPES = "content:read,content:write"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--role", required=True, help="岗位，如 concept / verifier / warden")
    ap.add_argument("--domain", required=True, help="域 key，如 legal")
    ap.add_argument("--scopes", default=DEFAULT_SCOPES,
                    help=f"逗号分隔，默认 {DEFAULT_SCOPES}；admin/* 一律拒绝")
    ap.add_argument("--label", default="", help="凭据标签，默认 '<role>@<domain>'")
    # 不用 argparse 的 choices 拦 lead：那条拒绝要说明白"为什么"（lead 是确认权
    # 的来源），argparse 只会吐一句 invalid choice。
    ap.add_argument("--member-role", default="expert",
                    help="域内角色（annotator|expert）；lead 会被拒绝")
    ap.add_argument("--revoke", action="store_true", help="只撤销该身份的凭据")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    identity = agent_ids.agent_identity(args.role, args.domain)
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    bad = agent_ids.forbidden_scopes(scopes)
    if bad:
        print(f"拒绝：智能体不得持有平台级权限 {bad}", file=sys.stderr)
        return 2
    if args.member_role == "lead":
        print("拒绝：lead 是确认权的来源，不能发给智能体", file=sys.stderr)
        return 2

    from src.eval.db import connect

    conn = connect()
    try:
        domain = workspaces.get_domain(conn, domain_key=args.domain)
        if domain is None:
            print(f"域 {args.domain!r} 不存在", file=sys.stderr)
            return 1
        if args.dry_run:
            print(f"[dry-run] 将登记 {identity}：domain_members role={args.member_role}，"
                  f"scopes={scopes}")
            return 0

        workspaces.add_member(
            conn, domain_id=domain["id"], user_id=identity,
            role=args.member_role, added_by="register_agent",
        )
        print(f"域成员：{identity} → {args.domain} role={args.member_role}")

        if args.revoke:
            # 逐把撤：apikey 只有单把撤销（revoke_key 需要 key_id + user_id），
            # 而"撤谁"必须按身份精确匹配，不能按前缀猜。
            keys = [k for k in apikey.list_keys(identity) if not k.get("revoked_at")]
            revoked = 0
            for k in keys:
                if apikey.revoke_key(k["id"], identity):
                    revoked += 1
            print(f"已撤销凭据：{revoked} 把（成员关系保留，便于审计）")
            return 0

        key = apikey.create_key(
            identity, args.label or f"{args.role}@{args.domain}", scopes
        )
        print()
        print("凭据（只显示这一次，请立刻存进 0600 的凭据文件，不要贴进任何文档/提交）：")
        print(f"  X-API-Key: {key}")
        print()
        print(f"身份：{identity}")
        print(f"scope：{scopes}（无 admin/*，因此不能确认提案、不能发布）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
