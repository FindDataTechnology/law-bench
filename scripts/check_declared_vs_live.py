#!/usr/bin/env python3
"""声明 vs live 返回的一致性校验（change lex-matter-spine 5.6 的比对侧）。

存在的理由：`declared_detail` 是人按一次调用手写的形状，它会**自己骗自己**。
2026-11-10 实测就是这个：`type_metadata.universal_dims` 当时被写成 `["string"]`，
真实返回是 `{"stance": ["pro_a","pro_b","balanced"]}`——单个样本 + 手抄，
两次都写成"想当然的形状"。本脚本把"想当然"变成红灯。

用法：
    # 1) 在 pod 内采集（另见 collect_live_surface.py）
    kubectl exec ... -- python3 scripts/collect_live_surface.py --out /tmp/live.json
    # 2) 在任意位置比对
    python3 scripts/check_declared_vs_live.py --live /tmp/live.json

判据分三档，退出码只认前两档：
  ✗ 缺失 / 多出 / 类型不符 —— 声明与实返回矛盾，退出 1；
  ? 未观测 —— 元素为空集（库里没数据），形状无法证明，只告警不判红
    （判红会把"数据空"当成"声明错"，那是另一类问题，见 5.2 的语料缺口）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "tool-surface.json"


def kind_of(declared: object) -> str:
    """把声明的写法归一到类型类别。

    声明里允许的写法：`"string"`、`"string|null"`、`"int"`、`"bool"`、`"array"`、
    `"array<...>"`、嵌套 list、嵌套 dict。
    """
    if isinstance(declared, dict):
        return "dict"
    if isinstance(declared, list):
        return "list"
    if isinstance(declared, str):
        text = declared.strip()
        if text.startswith("array"):
            return "list"
        if "|" in text:
            return "union"
        return text
    return type(declared).__name__


def compare(path: str, declared: object, live: object, problems: list, notes: list) -> None:
    dkind = kind_of(declared)

    # 「已声明形状，但本环境观测不到」的显式出口。
    #
    # 为什么要它：没有出口，遇到"声明是对的、只是这台环境造不出样本"时只剩两条歪路——
    # 把声明改成实测值（等于拿 null 冒充成功形状）或删掉声明（等于放弃契约）。
    # 两者都比"留一条待复采的记录"差。用法：`{"$unobservable": "<为什么观测不到>"}`，
    # 比对器只记旁注、不对形状下判断；原因必须写环境事实，不能写"暂时跳过"。
    if isinstance(declared, dict) and set(declared) == {"$unobservable"}:
        notes.append(f"{path}: 已声明但本环境不可观测 —— {declared['$unobservable']}")
        return

    if dkind == "union":
        allowed = {part.strip() for part in str(declared).split("|")}
        if isinstance(live, str) and live in allowed:
            return
        problems.append(f"{path}: 声明 {declared!r}，实返回 {live!r}")
        return

    if dkind == "dict":
        if not isinstance(live, dict):
            problems.append(f"{path}: 声明为对象，实返回 {type(live).__name__}")
            return
        if not declared:
            # 空对象声明 = "键随数据变化的映射"（如 sha256_by_format：产出的格式不同，
            # 键就不同）。只验它是对象，键留作旁注——按键逐个比会把合法的动态键判成
            # 多出未声明，那不是契约漂移。
            if live:
                notes.append(f"{path}: 动态键映射，实测键 {sorted(live)}（不逐键比对）")
            return
        for key, sub in declared.items():
            if key not in live:
                problems.append(f"{path}.{key}: 声明有、实返回无")
            else:
                compare(f"{path}.{key}", sub, live[key], problems, notes)
        extra = sorted(set(live) - set(declared))
        if extra:
            problems.append(f"{path}: 实返回多出未声明键 {extra}")
        return

    if dkind == "list":
        if not isinstance(live, list):
            problems.append(f"{path}: 声明为数组，实返回 {type(live).__name__}")
            return
        if not live:
            notes.append(f"{path}: 元素为空集，形状未观测（需有数据才能证明）")
            return
        # 声明的元素形状：list 里给一个模板；或 "array<...>" 无模板（只验是数组）
        if isinstance(declared, list) and declared:
            compare(f"{path}[]", declared[0], live[0], problems, notes)
        return

    # 标量：string / int / bool
    #
    # 注意：采集产物里的"值"本身就是类型令牌（`"bool"`、`"int"`、`"null"`），
    # 不是原始值。2026-11-10 首版拿 Python 类型名去比，10 件全报"声明 bool，实返回 str"——
    # 校验器自己的 bug 冒充了 10 处契约缺陷。令牌优先，非令牌才回退到真实类型名。
    TOKENS = {"string", "int", "bool", "float", "null"}
    actual = live if isinstance(live, str) and live in TOKENS else type(live).__name__
    if dkind == "int" and actual == "bool":
        # bool 是 int 的子类，误报比漏报更难查
        problems.append(f"{path}: 声明 int，实返回 bool")
        return
    if dkind != actual:
        problems.append(f"{path}: 声明 {dkind}，实返回 {actual}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", required=True, help="collect_live_surface.py 的产物")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    detail = manifest["output_structure"]["declared_detail"]
    live = json.loads(Path(args.live).read_text(encoding="utf-8"))
    live_tools = live.get("tools") or {}

    problems: list[str] = []
    notes: list[str] = []
    checked = 0

    for name, spec in detail.items():
        entry = live_tools.get(name)
        if entry is None:
            problems.append(f"{name}: 已声明但未采集（采集器未覆盖该工具）")
            continue
        if entry.get("error"):
            problems.append(f"{name}: 采集失败 —— {entry['error']}")
            continue
        if entry.get("isError"):
            problems.append(f"{name}: 调用返回 isError=true")
            continue
        envelope = spec.get("envelope", "structuredContent")
        if envelope != "structuredContent":
            problems.append(f"{name}: 声明 envelope={envelope!r}，本校验器只验 structuredContent")
            continue
        compare(name, spec.get("returns", {}), entry.get("shape", {}), problems, notes)
        checked += 1

    print(f"比对 {checked} 件（声明 {len(detail)} 件）")
    for note in notes:
        print(f"  ? {note}")
    if problems:
        print(f"\n✗ {len(problems)} 处不一致：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"\n✓ declared_detail 与 live 返回逐键一致（{checked} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
