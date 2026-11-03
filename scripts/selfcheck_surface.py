#!/usr/bin/env python3
"""tool-surface manifest 双向 selfcheck（mcp-surface-contract）。

断言两个方向：
  1. 一致：manifest 声明的工具 == 代码注册的工具；且每个工具的四个行为属性
     （readOnlyHint / destructiveHint / idempotentHint / openWorldHint）
     manifest ↔ 运行时逐项相等——谎报只读会让客户端自动批准一个会写库的工具
  2. 闭合：消费侧必需依赖（data_binding / mcp_servers 声明行）中的本 server
     工具 ⊆ manifest 的 commercial 集（optional_binding 为可选增强，不受约束）

代码注册面优先 `mcp.list_tools()` 运行时真值，不可导入时回退源码码点
（@mcp.tool 分布在 src 包根与 tools/ 子模块，rglob 全扫）。行为属性无法回退：
运行时不可导入即失败（无法核对比不核对更危险）。

用法：
    python3 scripts/selfcheck_surface.py
    python3 scripts/selfcheck_surface.py --consumers /path/to/skills
退出码：0 通过 / 1 失败（列出差异）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "tool-surface.json"
SERVER_NAME = "law-bench"
# The MCP package is a sub-project, not ``REPO/src`` (the shared venv also has
# an editable install pointing at another checkout, so the path insert must
# name this repo explicitly and come first).
PKG_SRC = REPO / "fd-coding-law-bench-mcp" / "src"
PKG = PKG_SRC / "fd_coding_law_bench_mcp"

TOOL_PATTERN = re.compile(rf"mcp__{SERVER_NAME}__([A-Za-z0-9_.\-]+)")
HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def fail(problems: list[str]) -> "None":
    print(f"✗ {len(problems)} 项不通过：", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    raise SystemExit(1)


def load_manifest() -> dict:
    if not MANIFEST.exists():
        fail([f"manifest 缺失：{MANIFEST}（契约：缺失即未上牌）"])
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def manifest_tools(m: dict) -> dict[str, str]:
    out = {}
    for g in m.get("tool_groups", []):
        level = g.get("level")
        if level not in ("commercial", "internal"):
            fail([f"tool_groups.{g.get('group')} 的 level 非法：{level!r}"])
        for t in g.get("tools", []):
            if t in out and out[t] != level:
                fail([f"工具 {t} 在多个 group 中级别冲突"])
            out[t] = level
    return out


async def runtime_tools() -> set[str]:
    names = await runtime_annotations()
    if names is None:
        return source_tools()
    return set(names)


async def runtime_annotations() -> dict[str, dict] | None:
    """Each registered tool's protocol-level hints; ``None`` if not importable."""
    sys.path.insert(0, str(PKG_SRC))
    try:
        from fd_coding_law_bench_mcp.server import mcp  # type: ignore

        tools = await mcp.list_tools()
    except Exception:
        return None
    out: dict[str, dict] = {}
    for t in tools:
        name = getattr(t, "name", None) or t.get("name")
        if not name:
            continue
        a = getattr(t, "annotations", None)
        out[name] = {} if a is None else {k: getattr(a, k) for k in HINTS}
    return out


def source_tools() -> set[str]:
    names: set[str] = set()
    for f in PKG.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        # The decorator args now nest parentheses (annotations_for("...")), so
        # match to the end of the decorator line instead of the first ")".
        for m in re.finditer(
            r"@mcp\.tool\(.*?\)\s*\n(?:\s*\n)*\s*(?:async\s+)?def\s+([A-Za-z0-9_]+)",
            text,
        ):
            names.add(m.group(1))
    return names


async def check_annotations(m: dict, declared: dict[str, str]) -> list[str]:
    """manifest ``tool_annotations`` ↔ runtime hints, both directions.

    Missing hints leave the client unable to decide auto-approval; a declared
    read-only hint on a writing tool makes it auto-approve a state change.
    Both are surfacing defects.
    """
    ann = m.get("tool_annotations")
    if not isinstance(ann, dict):
        return ["[属性缺失] manifest 缺 tool_annotations（行为属性须随工具一并上牌）"]
    runtime = await runtime_annotations()
    if runtime is None:
        return ["[无法核对] server 不可导入，行为属性无法与运行时比对"]

    problems: list[str] = []
    for name in sorted(set(declared) - set(ann)):
        problems.append(f"[属性缺失] {name}: manifest 未声明行为属性")
    for name in sorted(set(ann) - set(declared)):
        problems.append(f"[属性越界] {name}: tool_annotations 登记了未上牌的工具")
    for name in sorted(set(declared) & set(ann)):
        d = ann[name]
        missing = [k for k in HINTS if k not in d]
        if missing:
            problems.append(f"[属性不全] {name}: 缺 {', '.join(missing)}")
            continue
        rt = runtime.get(name, {})
        for k in HINTS:
            if rt.get(k) != d[k]:
                problems.append(
                    f"[属性不符] {name}.{k}: manifest 声明 {d[k]!r}，运行时 {rt.get(k)!r}"
                )
    return problems


def consumer_tools(consumers: list[Path]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for c in consumers:
        if not c.exists():
            fail([f"消费侧路径不存在：{c}"])
        used: set[str] = set()
        for f in list(c.rglob("*.json")) + list(c.rglob("*.md")):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for line in text.splitlines():
                if re.match(r"\s*(data_binding|mcp_servers)\s*:", line):
                    used |= set(TOOL_PATTERN.findall(line))
        if used:
            out[str(c)] = used
    return out
def check_output_structure(m: dict, declared: dict[str, str]) -> list[str]:
    """输出结构状态必须显式登记（mcp-result-contract「无静默空缺」）。

    本服务尚未逐工具声明输出结构（返回形状随输入变化，需先固化契约），故
    manifest 里登记为 `undeclared`。这条检查保证：新增工具时不会出现"既没声明、
    也没登记为未声明"的静默空缺——那种工具在客户端看来与已声明工具无从区分。

    日后某工具真的挂上 output_schema 时，本检查会失败并提示把它移进 declared：
    登记状态与运行时事实必须一致，不能靠记忆维护。
    """
    block = m.get("output_structure")
    if not isinstance(block, dict):
        return ["manifest 缺 output_structure（输出结构状态须显式可见）"]
    dec = set(block.get("declared") or [])
    und = set(block.get("undeclared") or [])
    problems: list[str] = []
    both = sorted(dec & und)
    if both:
        problems.append(f"同时出现在 declared 与 undeclared：{both}")
    silent = sorted(set(declared) - dec - und)
    if silent:
        problems.append(f"既未声明也未登记为未声明（静默空缺）：{silent}")
    stray = sorted((dec | und) - set(declared))
    if stray:
        problems.append(f"output_structure 登记了未上牌的工具：{stray}")
    return problems



async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consumers", nargs="*", type=Path, default=[])
    args = ap.parse_args()

    m = load_manifest()
    declared = manifest_tools(m)
    actual = await runtime_tools()
    problems: list[str] = []

    missing = sorted(actual - set(declared))
    stale = sorted(set(declared) - actual)
    if missing:
        problems.append(f"[注册表漂移] 代码已注册但 manifest 未声明：{', '.join(missing)}")
    if stale:
        problems.append(f"[manifest 陈旧] manifest 声明但代码未注册：{', '.join(stale)}")

    expected = m.get("registry", {}).get("expected_tool_count")
    if expected is not None and len(actual) != expected:
        problems.append(f"[工具数不符] 运行时 {len(actual)} ≠ manifest 声明 {expected}")

    problems += await check_annotations(m, declared)
    problems += check_output_structure(m, declared)

    internal = {t for t, lv in declared.items() if lv == "internal"}
    if args.consumers:
        for where, used in consumer_tools(args.consumers).items():
            over = sorted(used & internal)
            if over:
                problems.append(f"[消费侧越界] {where} 必需依赖点名了 internal 工具：{', '.join(over)}")

    commercial = sorted(t for t, lv in declared.items() if lv == "commercial")
    print(f"manifest：{len(declared)} 工具（commercial {len(commercial)} / internal {len(internal)}）")
    print(f"运行时：{len(actual)} 工具")
    ann = m.get("tool_annotations") or {}
    read_only = sum(1 for v in ann.values() if v.get("readOnlyHint") is True)
    print(f"行为属性：{len(ann)} 工具已声明（只读 {read_only} / 写 {len(ann) - read_only}）")
    if problems:
        fail(problems)
    print("✓ selfcheck 双向断言通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
