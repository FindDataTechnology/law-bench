"""限流的 IP 键必须取 `X-Forwarded-For` 的**最后一跳**，不是第一跳。

`_caller_id` 在无 API key 时回落到 IP，用 `forwarded.split(",")[0]` 取第一跳。
但前面那层代理（cheap1 的雷池 nginx）用的是
`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`——**追加**语义：

    客户端伪造成  X-Forwarded-For: 1.2.3.4
    代理追加真实源 → X-Forwarded-For: 1.2.3.4, <真实源 IP>

所以 `[0]` 取到的正是客户端**自己写的假值**：每次请求换一个假 IP 就是一批新桶，
速率限制形同不存在（不仅绕过，还会把桶表灌满，触发淘汰把别人正在限流的桶挤掉）。

取 `[-1]` 才是"离我们最近的那一跳"，由我们自己的代理写入，客户端改不了。

适用前提（已核实）：前面确实只有一层可信代理，且它用追加语义
（`$proxy_add_x_forwarded_for`）。若将来加了一层或多层，这条要跟着调。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.web.rate_limit import _caller_id  # noqa: E402


class _Req:
    """最小 Request 替身：只要 headers 和 client.host。"""

    def __init__(self, headers=None, client_host="10.9.9.9"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": client_host})()


def test_forged_first_hop_does_not_change_the_key():
    """客户端伪造第一跳，键必须不变（取最后一跳）。"""
    forged_a = _Req({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    forged_b = _Req({"X-Forwarded-For": "5.6.7.8, 203.0.113.7"})
    assert _caller_id(forged_a) == _caller_id(forged_b), (
        "换一个伪造的第一跳就换了一个限流桶 —— 攻击者可以无限绕过速率限制"
    )


def test_key_uses_the_real_client_from_the_last_hop():
    """键里应当是代理追加的真实源。"""
    req = _Req({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    assert "203.0.113.7" in _caller_id(req)


def test_api_key_still_wins_over_ip():
    """有 API key 时按 key 前缀计，IP 那条路不生效（原行为不变）。"""
    req = _Req({"X-API-Key": "abcdefghijklmnopqrstuvwxyz", "X-Forwarded-For": "1.2.3.4"})
    assert _caller_id(req).startswith("k:")


def test_no_forwarded_header_falls_back_to_peer_ip():
    """没有 XFF 时回落到对端地址（原行为不变）。"""
    assert "10.9.9.9" in _caller_id(_Req({}))
