"""岗位注册表：一条线能跑哪些岗位，由该线的 pack 声明。

内核只认七个岗位名与三个参数形状（是否启用、节奏、岗位自己的域参数），
**不认识任何行业**——所以加一条线 = 加一段 yaml，不改编排层。

为什么参数必须在 pack 里而不是编排层：法律线与政务线要的文种、语料形状、
接地要求完全不同。写在编排层，第二条线就要改代码；写成 `if domain == ...`，
第三条线就要改第二个地方。这和 `entity_keys` 的注册表、`ingest_rule.document`
是同一个思路：内核给机制，域给参数。

未声明的线**不启动**，并如实说"未声明"——不套用别的线的默认值。给一个沉默的
默认，等于替业务做它没做的决定。
"""

from __future__ import annotations

from typing import Any, Optional

from . import packs

#: 固定岗位词表。多一个名字就是多一份权限面，所以词表是闭的。
ROLES: tuple[str, ...] = ("scout", "builder", "concept", "verifier", "eval", "release", "warden")

#: 没有声明节奏时的兜底（分钟）。只对只读岗位给默认——写类岗位必须显式声明，
#: 因为"多久写一次"是业务决定，不是内核的。
DEFAULT_CADENCE_MINUTES: dict[str, int] = {"warden": 15, "verifier": 60}

#: 岗位可以声明的参数键（每种岗位认自己那几个）。出现未知键即报错：拼写错误
#: 静默被忽略，是最难查的一类配置事故。
ROLE_PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "scout": ("doc_types", "sources", "limit"),
    "builder": ("doc_types", "sources"),
    # 概念岗也要能声明语料面：概念只从某类语料里来，声明在哪由该线决定。
    "concept": ("batch_chunks", "min_usable_rate", "max_total", "sources"),
    "verifier": ("checks",),
    "eval": ("suites",),
    "release": ("require_digest_match",),
    "warden": ("review_threshold_hours",),
}


class RoleDeclarationError(ValueError):
    """pack 里的 roles 段不合法（未知岗位、未知参数、类型不对）。"""


def declared_roles(manifest: dict, *, pack_name: str = "") -> dict[str, dict]:
    """把 pack.yaml 的 ``roles`` 段规范化；不合法即抛，不静默丢弃。"""
    raw = (manifest or {}).get("roles")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RoleDeclarationError(
            f"pack {pack_name!r} 的 roles 必须是映射，实际是 {type(raw).__name__}"
        )
    out: dict[str, dict] = {}
    for name, spec in raw.items():
        if name not in ROLES:
            raise RoleDeclarationError(
                f"pack {pack_name!r} 声明了未知岗位 {name!r}；可用岗位：{list(ROLES)}"
            )
        if spec is None:
            spec = {}
        if not isinstance(spec, dict):
            raise RoleDeclarationError(
                f"pack {pack_name!r} 的岗位 {name!r} 必须是映射"
            )
        unknown = set(spec) - set(ROLE_PARAM_KEYS[name]) - {"enabled", "cadence_minutes"}
        if unknown:
            raise RoleDeclarationError(
                f"pack {pack_name!r} 的岗位 {name!r} 有未知参数 {sorted(unknown)}；"
                f"可用参数：{sorted(ROLE_PARAM_KEYS[name] + ('enabled', 'cadence_minutes'))}"
            )
        enabled = spec.get("enabled", True)
        if not isinstance(enabled, bool):
            raise RoleDeclarationError(
                f"pack {pack_name!r} 的岗位 {name!r}：enabled 必须是布尔"
            )
        cadence = spec.get("cadence_minutes")
        if cadence is not None and (not isinstance(cadence, int) or cadence <= 0):
            raise RoleDeclarationError(
                f"pack {pack_name!r} 的岗位 {name!r}：cadence_minutes 必须是正整数"
            )
        out[name] = {"enabled": enabled, "cadence_minutes": cadence,
                     **{k: v for k, v in spec.items()
                        if k in ROLE_PARAM_KEYS[name]}}
    return out


def roles_for_domain(domain_key: str) -> dict:
    """该域声明了哪些岗位。未声明/无 pack 都返回 ``declared=False`` 并说明原因。

    不做"按名字猜 pack"以外的推断：域 key 与 pack 目录同名是本仓的既有约定
    （``packs.legal`` 给 ``legal`` 注册规则），猜错了比不猜更糟。
    """
    try:
        manifest = packs.load_pack(domain_key)
    except FileNotFoundError:
        return {"declared": False, "roles": {},
                "reason": f"该域没有 pack（packs/{domain_key}/pack.yaml 不存在），岗位参数未声明"}
    except ValueError as exc:
        return {"declared": False, "roles": {}, "reason": str(exc)}
    try:
        roles = declared_roles(manifest, pack_name=domain_key)
    except RoleDeclarationError as exc:
        return {"declared": False, "roles": {}, "reason": str(exc)}
    if not roles:
        return {"declared": False, "roles": {},
                "reason": f"pack {domain_key!r} 没有 roles 段，岗位参数未声明"}
    return {"declared": True, "roles": roles, "reason": None}


def cadence_minutes(role: str, spec: dict) -> Optional[int]:
    """该岗位的节奏；写类岗位没声明就是 ``None``（不猜）。"""
    declared = spec.get("cadence_minutes")
    if declared:
        return int(declared)
    return DEFAULT_CADENCE_MINUTES.get(role)


def plan(domain_key: str) -> dict:
    """编排层唯一入口：这条线该起哪些岗位、各多久一次、哪些没起及原因。

    纯读，不写任何东西——"计划"与"执行"分开，页面刷新不会变成一次部署。
    """
    declared = roles_for_domain(domain_key)
    if not declared["declared"]:
        return {"domain_key": domain_key, "declared": False,
                "reason": declared["reason"], "runnable": [], "skipped": list(ROLES)}
    runnable, skipped = [], []
    for role in ROLES:
        spec = declared["roles"].get(role)
        if spec is None:
            skipped.append(role)          # 未声明 = 不起
            continue
        if not spec.get("enabled"):
            skipped.append(role)          # 显式关闭
            continue
        runnable.append({"role": role, "cadence_minutes": cadence_minutes(role, spec),
                         "params": {k: v for k, v in spec.items()
                                    if k not in ("enabled", "cadence_minutes")}})
    return {"domain_key": domain_key, "declared": True, "reason": None,
            "runnable": runnable, "skipped": skipped}
