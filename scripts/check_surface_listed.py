#!/usr/bin/env python3
"""上牌断言：注册表 ↔ 仓内清单 ↔ 现网 tools/list 三方一致（lex-matter-spine 5.7）。

三处数字为什么会分叉（都踩过）：
- **仓内清单**（`tool-surface.json`）是声明面，改了代码没改它就会偏；
- **现网 tools/list** 是运行时真值，但只有滚到新镜像才变；
- **注册表条目**是给市场/发布门看的快照，只在有人 PATCH 时才更新。

任取两方比对都会漏：清单=注册表 可能两边一起旧；现网=注册表 可能都旧于代码。
所以三条都要，且**集合**要比（只比数字会让"数量对、名字错"过关）。

用法（需 gateway token 读注册表；活栈地址见 MCP-REGISTRY.md 的切流记录）：
    python3 scripts/check_surface_listed.py \
        --registry http://100.64.0.15:18080 \
        --live /tmp/live_tools.json          # pod 内 tools/list 的落盘结果

`--live` 不给则跳过现网一环（只做清单↔注册表），并在输出里明说跳过。
退出码：0 三方一致 / 1 任一不符（逐条指名差集）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "tool-surface.json"
SERVER_PATH = "/law-bench"
TOKEN_FILE = Path.home() / ".config" / "finddata" / "gateway-token.json"


def gateway_token() -> str | None:
    """读 gateway token；缺失时返回 None（注册表可能允许匿名读）。"""
    if not TOKEN_FILE.is_file():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))["tokens"]["access_token"]
    except (KeyError, json.JSONDecodeError):
        return None


def fetch_registry(base: str, path: str) -> dict:
    request = urllib.request.Request(f"{base.rstrip('/')}/api/servers{path}")
    token = gateway_token()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body[0] if isinstance(body, list) else body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True, help="注册表基址，如 http://100.64.0.15:18080")
    ap.add_argument("--path", default=SERVER_PATH)
    ap.add_argument("--live", help="pod 内 tools/list 的 JSON 落盘（[{name,description},...]）")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    man_all = {t for group in manifest["tool_groups"] for t in group.get("tools", [])}
    man_commercial = sorted(
        t for group in manifest["tool_groups"] if group.get("level") == "commercial"
        for t in group.get("tools", [])
    )

    registry = fetch_registry(args.registry, args.path)
    raw = registry.get("tool_list") or []
    reg_all = {x["name"] if isinstance(x, dict) else x for x in raw}
    reg_commercial = sorted(((registry.get("metadata") or {}).get("surface") or {}).get("commercial_tools") or [])

    problems: list[str] = []
    notes: list[str] = []

    if registry.get("num_tools") != len(reg_all):
        problems.append(f"注册表自相矛盾：num_tools={registry.get('num_tools')} 但 tool_list={len(reg_all)}")
    if reg_all != man_all:
        problems.append(f"清单↔注册表 工具集不同：清单独有 {sorted(man_all - reg_all)} / 注册表独有 {sorted(reg_all - man_all)}")
    if reg_commercial != man_commercial:
        problems.append(f"商业集不同：清单独有 {sorted(set(man_commercial) - set(reg_commercial))} / 注册表独有 {sorted(set(reg_commercial) - set(man_commercial))}")

    live_count: int | None = None
    if args.live:
        live_raw = json.loads(Path(args.live).read_text(encoding="utf-8"))
        live_all = {x["name"] if isinstance(x, dict) else x for x in live_raw}
        live_count = len(live_all)
        if live_all != man_all:
            problems.append(f"清单↔现网 工具集不同：现网独有 {sorted(live_all - man_all)} / 清单独有 {sorted(man_all - live_all)}")
        if not set(reg_commercial) <= live_all:
            problems.append(f"商业集里这些工具现网没有：{sorted(set(reg_commercial) - live_all)}")
    else:
        notes.append("未给 --live：跳过『现网 tools/list』一环（清单↔注册表仍已校验）")

    print(f"清单 {len(man_all)}（商业 {len(man_commercial)}）"
          f" | 注册表 {registry.get('num_tools')}（商业 {len(reg_commercial)}）"
          f" | 现网 {live_count if live_count is not None else '未校验'}")
    for note in notes:
        print(f"  ? {note}")
    if problems:
        print(f"\n✗ {len(problems)} 处不符：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\n✓ 三方一致（清单 = 注册表 = 现网），商业集在现网可寻")
    return 0


if __name__ == "__main__":
    sys.exit(main())
