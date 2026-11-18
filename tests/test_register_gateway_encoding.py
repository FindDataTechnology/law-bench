"""MCP 网关注册脚本必须能把**数组**发出去（审计 03 §6）。

`_registration_fields()` 返回 `"supported_transports": ["streamable-http"]`，
注释还专门解释过：registry 原样存这个字段、探针按**数组**读，写成字符串
「once poisoned every row to unhealthy/degraded gateway-wide（2026-11-07 事故）」。

但 `_gateway_request()` 里是 `urllib.parse.urlencode(data)`，**没有 `doseq=True`**。
`urlencode` 遇到 list 会 `str(list)`，即 Python 的 `repr`：

    urlencode({'supported_transports': ['streamable-http']})
    → supported_transports=%5B%27streamable-http%27%5D      # 文本 ['streamable-http']

（本机实测，见下。）所以数组从没离开过进程：网关收到的是**一个标量**，
值就是 `['streamable-http']` 这一串带引号的文本——正是注释说绝不能出现的那种形状。

**为什么不 import 脚本跑行为测试**：它是 CLI 脚本，import 会触发 argparse 之外
的路径依赖。这里用源码断言 + 一个纯 `urlencode` 的行为对照，两件事都钉住：
①脚本里那处调用必须带 `doseq=True`；②带上之后确实产出重复键而不是 repr。
"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = (REPO / "scripts" / "infra" / "register_mcp_gateway.py").read_text(encoding="utf-8")


def test_urlencode_call_uses_doseq():
    """`_gateway_request` 里编码表单时必须 `doseq=True`，否则 list 被 repr 成标量。"""
    calls = re.findall(r"urllib\.parse\.urlencode\(([^)]*)\)", SRC)
    assert calls, "没找到 urlencode 调用（脚本结构变了？）"
    # 至少有一处是在编码注册表单（含 data），且必须带 doseq
    assert any("doseq=True" in c for c in calls), (
        "urlencode 没有 doseq=True —— list 会被 str() 成 "
        "['streamable-http'] 这样的文本标量，数组永远发不出去"
    )


def test_registration_fields_declares_an_array():
    """前提：`_registration_fields` 里该字段确实是 list（不是字符串）。

    如果哪天有人把它改成字符串，上面那条 doseq 检查就失去意义了——这条守住前提。
    """
    m = re.search(r'"supported_transports":\s*(\[[^\]]*\]|"[^"]*")', SRC)
    assert m, "没找到 supported_transports 的声明"
    assert m.group(1).startswith("["), (
        f"supported_transports 被写成标量 {m.group(1)} —— "
        "注释说过这个形状会在 2026-11-07 那种事故里整排污染"
    )


def test_doseq_produces_a_repeatable_key_not_repr():
    """行为对照：doseq=True 产出可重复键；不加则产出 Python repr。"""
    data = {"supported_transports": ["streamable-http"]}
    without = urllib.parse.urlencode(data)
    with_doseq = urllib.parse.urlencode(data, doseq=True)
    assert "%5B%27" in without, "预期不加 doseq 时出现 repr 的单引号（%27）"
    assert with_doseq == "supported_transports=streamable-http"
    assert "[" not in with_doseq and "%27" not in with_doseq
