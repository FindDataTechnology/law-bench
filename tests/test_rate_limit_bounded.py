"""限流的桶表必须有上界——否则攻击者用随机 key 就能把它撑爆。

中间件**在鉴权之前**跑（这是设计：它要保护鉴权本身），所以任何 key 都会被接受；
`_caller_id` 又优先用 `X-API-Key[:16]` 做键。一个每请求换一个随机 16 字符 key 的
bot，就是每请求新建一个桶——旧实现 `_buckets[caller] = b` 从不删除，docstring 里
"working set 由不同 caller 数界定、这个数很小"对诚实流量成立，对这条流量不成立。

同时钉住一条**不能引入新绕过**的性质：淘汰必须优先丢「已回满」的桶。一个满桶
与从未见过的 caller 无法区分，丢它不损失任何限流状态；反过来如果淘汰会丢掉
正在被限速的桶，攻击者只要刷 key 就能把自己那个空桶洗掉——把内存修复变成新绕过。
"""
from __future__ import annotations

import sys
import time

import pytest

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.web.rate_limit import TokenBucketLimiter  # noqa: E402


def test_bucket_map_is_bounded_under_a_key_flood():
    """刷 10 倍上限的随机 key，桶表不许超过上限。"""
    lim = TokenBucketLimiter(rps=1.0, burst=1, max_buckets=100)
    for i in range(1000):
        lim.allow(f"k:flood{i:011d}")
    assert len(lim._buckets) <= 100, f"桶表无界增长：{len(lim._buckets)}"


def test_eviction_prefers_refilled_buckets():
    """回满的桶先被丢；正在被限速的桶必须活下来。"""
    # 回填率必须很低：rps 高了 victim 的桶几乎立刻回满，"丢掉它"不损失任何状态，
    # 也就测不出淘汰是否错误地丢了活跃桶。
    lim = TokenBucketLimiter(rps=0.0001, burst=2, max_buckets=4)

    # 把 victim 打空：burst=2，连打三次后 tokens≈0 且几乎不回填
    lim.allow("k:victim000000001")
    lim.allow("k:victim000000001")
    allowed_third, _ = lim.allow("k:victim000000001")
    assert allowed_third is False, "victim 应已被限速"

    # 再塞进足够多的新 caller 触发多轮淘汰
    for i in range(50):
        lim.allow(f"k:newcomer{i:09d}")

    assert len(lim._buckets) <= 4
    # victim 若被淘汰，下一个请求会拿到全新满桶 → 重新放行，等于绕过
    again, _ = lim.allow("k:victim000000001")
    assert again is False, "正在被限速的桶被淘汰了——刷 key 即可重置自己的限速"


def test_no_eviction_below_the_ceiling():
    """没到上限时不许丢任何桶（正常流量不该被淘汰影响）。"""
    lim = TokenBucketLimiter(rps=1.0, burst=5, max_buckets=100)
    for i in range(10):
        lim.allow(f"k:calm{i:011d}")
    assert len(lim._buckets) == 10


def test_default_ceiling_is_finite(monkeypatch):
    """默认值必须有限（否则等于没修）。"""
    from src import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_MAX_BUCKETS", 50000)
    lim = TokenBucketLimiter(rps=1.0, burst=1)
    assert lim._max_buckets == 50000
