"""智能体身份的识别口径（一个前缀，两处闸门共用）。

为什么单独一个模块：**同一个判断要用在两个互不依赖的地方**——

- ``apikey.create_key`` 铸凭据时不许给智能体 ``admin``/``*``；
- ``proposals.confirm`` 确认提案时不许智能体当签字人，且管理员豁免对智能体
  提交的提案无效。

如果两处各写一遍 ``startswith("agent:")``，它们迟早会漂移：一处改了前缀，另一处
还认得旧写法，闸门就静默失效。这里只有一个字符串常量，改它等于同时改两处。

身份形如 ``agent:<role>@<domain>``，例如 ``agent:concept@legal``。它是普通域成员
（``role=expert``），不是平台管理员——这条由铸凭据时的闸保证，不靠约定。
"""

from __future__ import annotations

from typing import Optional

#: 所有智能体身份共用的前缀。改它会让既有凭据失效，因此不轻易改。
AGENT_PREFIX = "agent:"

#: 不允许智能体持有的平台级权限。
FORBIDDEN_FOR_AGENTS = frozenset({"admin", "*"})

#: 「机器身份」的类别前缀——``confirm`` 这类**只能由人做**的动作按这一族拦。
#:
#: 为什么需要它（2026-11-14 生产实历，我自己撞的）：``confirm`` 原来只拦
#: ``is_agent(actor)``，也就是**只认 ``agent:`` 这一个前缀**。于是任何别的机器形状的
#: 字符串都能当签字人——我在产库上用 ``actor="fleet:probe"`` 调了一次
#: ``proposals.confirm``，本意是「验证闸拦不拦」，结果它**通过了**：提案被确认、内核
#: 写出了一条 ``legal/国债`` 单元、审计里留下 ``operator="fleet:probe"``。规则的本意是
#: 「确认是人类 lead 的职责」，按名字前缀只挡一类机器身份，等于把「谁是机器」交给了
#: 调用方拼字符串。
#:
#: 词表与 :mod:`src.bench.submitters` 的 ``PREFIX_*`` 是同一族（那里按来源分类，这里按
#: 签字人分类，语义同源）。两者一致性由 ``tests/test_agent_ids.py`` 钉住——**别在这里
#: 手加前缀而不改那条测试**，那正是这个模块开头警告的漂移。
MACHINE_PREFIXES = (AGENT_PREFIX, "fleet:", "extract:")


def is_agent(identity: Optional[str]) -> bool:
    """``True`` when ``identity`` is an agent identity (empty/None is not)."""
    return bool((identity or "").strip().startswith(AGENT_PREFIX))


def is_machine(identity: Optional[str]) -> bool:
    """``True`` when ``identity`` is any machine-shaped identity, not just an agent.

    用于「只能由人做」的动作（提案确认、管理员豁免背书）：机器身份一律不得签字，
    无论它是 ``agent:`` / ``fleet:`` / ``extract:`` 中的哪一类。
    """
    ident = (identity or "").strip()
    return any(ident.startswith(prefix) for prefix in MACHINE_PREFIXES)


def agent_identity(role: str, domain_key: str) -> str:
    """构造标准身份串：``agent:<role>@<domain>``。

    两个分量都不许为空、不许含空白或 ``@``——身份一旦带歧义，审计里就分不清
    是哪个岗位在哪条线上做的那件事。
    """
    role = (role or "").strip()
    domain_key = (domain_key or "").strip()
    if not role or not domain_key:
        raise ValueError("智能体身份需要 role 与 domain_key")
    for name, value in (("role", role), ("domain_key", domain_key)):
        if "@" in value or any(ch.isspace() for ch in value):
            raise ValueError(f"{name} 不得包含 '@' 或空白：{value!r}")
    return f"{AGENT_PREFIX}{role}@{domain_key}"


def forbidden_scopes(scopes: Optional[list[str]]) -> list[str]:
    """该身份不允许持有的 scope 中，实际给出的那些（空表示合规）。"""
    return sorted(FORBIDDEN_FOR_AGENTS.intersection(scopes or []))
