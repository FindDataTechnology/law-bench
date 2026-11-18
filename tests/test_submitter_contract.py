"""提交方判定的穷举测试（纯函数，不需要数据库）。

这个模块存在的意义就是**每一类来源凭什么可信**，所以测试必须逐类穷举，而不是
抽两三条代表性用例：判定的失效方式不是抛异常，是悄悄放行一个本该拒绝的类别。
"""

from __future__ import annotations

import pytest

from src.bench import submitters as s


DOMAIN = "legal"


# ---------------------------------------------------------------- 分类

def test_classify_fleet():
    prefix, parts, bad = s.classify_source("fleet:fleet_1/m_2")
    assert prefix == s.PREFIX_FLEET and not bad
    assert parts == {"fleet_id": "fleet_1", "post_id": "m_2"}


def test_classify_fleet_real_shape_from_production():
    """生产库里的真实形状（含下划线、长度）必须能解析。"""
    prefix, parts, bad = s.classify_source(
        "fleet:fleet_1794335712751_wfa3ww/m_1794335712751_10rte4")
    assert not bad
    assert parts["fleet_id"] == "fleet_1794335712751_wfa3ww"


def test_classify_extract_real_shape_from_production():
    prefix, parts, bad = s.classify_source("extract:deepseek-v4.1-flash:2026-11-09.1")
    assert not bad
    assert parts == {"model": "deepseek-v4.1-flash", "prompt_version": "2026-11-09.1"}


def test_classify_agent():
    prefix, parts, bad = s.classify_source("agent:concept@legal")
    assert not bad and parts == {"role": "concept", "domain": "legal"}


@pytest.mark.parametrize("src", [
    "fleet:fleet_1",              # 没有 /post
    "fleet:/m_2",                 # 空 fleet_id
    "fleet:fleet_1/",             # 空 post
    "extract:model-only",         # 没有第二个冒号
    "extract::2026-11-09.1",      # 空 model
    "extract:m:a:b",              # 多一段
    "agent:concept",              # 没有 @
    "agent:@legal",               # 空 role
    "agent:concept@",             # 空 domain
    "agent:concept@legal@x",      # 多一个 @
])
def test_classify_malformed(src):
    prefix, parts, bad = s.classify_source(src)
    assert prefix is not None and parts is None and bad is True, src


@pytest.mark.parametrize("src", ["", None, "wire:foo/bar", "Fleet:a/b", "extractx:a:b", "agentx:a@b"])
def test_classify_unknown_prefix(src):
    prefix, parts, bad = s.classify_source(src)
    assert prefix is None and parts is None and bad is False, src


# ---------------------------------------------------------------- fleet

def test_fleet_ok():
    assert s.verdict("fleet:f1/p1", domain_key=DOMAIN, via=s.VIA_HTTP,
                     fleet={"domains": ["legal"], "revoked": False}) == "ok"


def test_fleet_unregistered():
    assert s.verdict("fleet:f1/p1", domain_key=DOMAIN, via=s.VIA_HTTP,
                     fleet=None) == "unregistered"


def test_fleet_revoked():
    assert s.verdict("fleet:f1/p1", domain_key=DOMAIN, via=s.VIA_HTTP,
                     fleet={"domains": ["legal"], "revoked": True}) == "revoked"


def test_fleet_domain_mismatch():
    assert s.verdict("fleet:f1/p1", domain_key=DOMAIN, via=s.VIA_HTTP,
                     fleet={"domains": ["gov"], "revoked": False}) == "domain_mismatch"


def test_fleet_empty_domains_is_mismatch():
    assert s.verdict("fleet:f1/p1", domain_key=DOMAIN, via=s.VIA_HTTP,
                     fleet={"domains": [], "revoked": False}) == "domain_mismatch"


# ---------------------------------------------------------------- extract

def test_extract_in_process_ok():
    assert s.verdict("extract:m:2026-11-09.1", domain_key=DOMAIN,
                     via=s.VIA_IN_PROCESS) == "ok"


def test_extract_over_http_is_impersonation():
    """这是整个模块最重要的一条：外部通道写 extract: 一律拒绝。"""
    assert s.verdict("extract:m:2026-11-09.1", domain_key=DOMAIN,
                     via=s.VIA_HTTP) == "pipeline_impersonation"


def test_extract_ignores_fleet_registration():
    """给 extract: 配一条登记也不能放行外部提交。"""
    assert s.verdict("extract:m:v", domain_key=DOMAIN, via=s.VIA_HTTP,
                     fleet={"domains": [DOMAIN], "revoked": False}) == "pipeline_impersonation"


# ---------------------------------------------------------------- agent

def test_agent_ok():
    assert s.verdict("agent:concept@legal", domain_key=DOMAIN, via=s.VIA_HTTP,
                     agent_is_member=True) == "ok"


def test_agent_domain_mismatch():
    assert s.verdict("agent:concept@gov", domain_key=DOMAIN, via=s.VIA_HTTP,
                     agent_is_member=True) == "agent_domain_mismatch"


def test_agent_not_member():
    assert s.verdict("agent:concept@legal", domain_key=DOMAIN, via=s.VIA_HTTP,
                     agent_is_member=False) == "agent_not_member"


def test_agent_cannot_use_extract_channel():
    """agent: 走进程内通道也照常按身份判，不因通道放宽。"""
    assert s.verdict("agent:concept@legal", domain_key=DOMAIN, via=s.VIA_IN_PROCESS,
                     agent_is_member=False) == "agent_not_member"


# ---------------------------------------------------------------- 通道等价

def test_unknown_prefix_rejected_on_both_channels():
    for via in (s.VIA_HTTP, s.VIA_IN_PROCESS):
        assert s.verdict("wire:a/b", domain_key=DOMAIN, via=via) == "unknown_prefix"


def test_malformed_rejected_on_both_channels():
    for via in (s.VIA_HTTP, s.VIA_IN_PROCESS):
        assert s.verdict("fleet:no-slash", domain_key=DOMAIN, via=via) == "malformed"


# ---------------------------------------------------------------- 结论词表

def test_verdicts_are_from_the_declared_vocabulary():
    """任何分支都不许返回词表外的结论——上层按这个词表做错误映射。"""
    seen = set()
    cases = [
        ("fleet:f/p", {"fleet": {"domains": ["legal"], "revoked": False}}),
        ("fleet:f/p", {"fleet": None}),
        ("fleet:f/p", {"fleet": {"domains": ["legal"], "revoked": True}}),
        ("fleet:f/p", {"fleet": {"domains": ["gov"], "revoked": False}}),
        ("extract:m:v", {"via": s.VIA_HTTP}),
        ("extract:m:v", {"via": s.VIA_IN_PROCESS}),
        ("agent:r@gov", {"agent_is_member": True}),
        ("agent:r@legal", {"agent_is_member": False}),
        ("agent:r@legal", {"agent_is_member": True}),
        ("user:a@b", {"authenticated_as": "other@b"}),
        ("user:a@b", {"authenticated_as": "a@b"}),
        ("nope", {}),
        ("fleet:", {}),
    ]
    for src, extra in cases:
        kw = {"domain_key": DOMAIN, "via": s.VIA_HTTP}
        kw.update(extra)
        got = s.verdict(src, **kw)
        assert got in s.VERDICTS, (src, got)
        seen.add(got)
    assert seen == set(s.VERDICTS), f"未覆盖的结论：{set(s.VERDICTS) - seen}"


def test_is_allowed_only_ok():
    for v in s.VERDICTS:
        assert s.is_allowed(v) is (v == "ok")
