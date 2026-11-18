"""提交方身份的判定（纯函数，零 DB 依赖）。

**为什么单独一个模块**：这条判定要在进程内与 HTTP 两个调用点用同一份逻辑，而
它最容易错的地方不是查表，是**哪一类来源凭什么可信**。三类来源的可信依据完全
不同：

- ``fleet:<fleet_id>/<post_id>`` —— 外部提交方，凭**登记 + 凭据**（登记绑定域、
  可吊销）。这是唯一允许走外部 HTTP 的类别。
- ``extract:<model>:<prompt_version>`` —— 抽取流水线，凭**调用位置**。它由
  ``src/bench/extraction.py`` 在进程内调用，没有凭据可验；因此它的可信依据就是
  「不在网络面上」。外部端点必须拒绝该类，否则任何人把来源写成 ``extract:任意``
  即可冒充流水线。
- ``agent:<role>@<domain>`` —— 平台自铸身份（``agent_ids.py``），凭**已铸凭据 +
  域成员身份**。自报该前缀会让「自提自确认禁令」在错误身份上生效。

把三类压成一条「有登记就放行」的规则会同时放过冒充者、拒掉真正的生产者（生产库
实测：93 条提案里 78 条是 ``extract:`` 前缀的流水线产物）。

判定与查表分开：本模块只做判断，调用方负责把登记行与成员事实取来。这样判定可以
在没有任何数据库的情况下被穷举测试——而这正是它必须被穷举的理由。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

#: 来源前缀。改它们等于改契约，不轻改。
PREFIX_FLEET = "fleet:"
PREFIX_EXTRACT = "extract:"
PREFIX_AGENT = "agent:"
PREFIX_USER = "user:"

#: 提交通道。``extract:`` 只在 ``in_process`` 下被接受。
VIA_HTTP = "http"
VIA_IN_PROCESS = "in_process"

#: 判定结论。每一个都对应一句能对提交方说清的话，不留「其它」。
VERDICTS: tuple[str, ...] = (
    "ok",
    "unregistered",          # fleet：没有这条登记
    "revoked",               # fleet：登记已吊销
    "domain_mismatch",       # fleet：登记未绑定目标域
    "pipeline_impersonation",  # extract：从外部通道提交
    "agent_domain_mismatch",  # agent：身份里的域与目标域不一致
    "agent_not_member",      # agent：身份不在该域活跃成员里
    "user_mismatch",         # user：自称的身份不是本次请求的认证身份
    "malformed",             # 前缀认得，形状不完整
    "unknown_prefix",        # 四类之外
)

#: 需要按类别报明给提交方的形状要求（拼错前缀时就列这个）。
SHAPES: dict[str, str] = {
    PREFIX_FLEET: "fleet:<fleet_id>/<post_id>",
    PREFIX_EXTRACT: "extract:<model>:<prompt_version>",
    PREFIX_AGENT: "agent:<role>@<domain>",
    PREFIX_USER: "user:<identity>",
}


def classify_source(source: Optional[str]) -> Tuple[Optional[str], Optional[dict], bool]:
    """把来源拆成 ``(prefix, parts, malformed)``。

    ``prefix`` 为 ``None`` 表示不属于任何一类；``malformed`` 表示前缀认得但形状
    不完整（例如 ``fleet:`` 后面没有 ``/``）。两者都拒绝，但报的话不同。
    """
    text = (source or "").strip()
    if text.startswith(PREFIX_FLEET):
        rest = text[len(PREFIX_FLEET):]
        fleet_id, sep, post_id = rest.partition("/")
        if not sep or not fleet_id or not post_id:
            return PREFIX_FLEET, None, True
        return PREFIX_FLEET, {"fleet_id": fleet_id, "post_id": post_id}, False

    if text.startswith(PREFIX_EXTRACT):
        rest = text[len(PREFIX_EXTRACT):]
        model, sep, version = rest.partition(":")
        if not sep or not model or not version or ":" in version:
            return PREFIX_EXTRACT, None, True
        return PREFIX_EXTRACT, {"model": model, "prompt_version": version}, False

    if text.startswith(PREFIX_AGENT):
        rest = text[len(PREFIX_AGENT):]
        role, sep, domain = rest.partition("@")
        if not sep or not role or not domain or "@" in domain:
            return PREFIX_AGENT, None, True
        return PREFIX_AGENT, {"role": role, "domain": domain}, False

    if text.startswith(PREFIX_USER):
        identity = text[len(PREFIX_USER):]
        if not identity or any(ch.isspace() for ch in identity):
            return PREFIX_USER, None, True
        return PREFIX_USER, {"identity": identity}, False

    return None, None, False


def verdict_for_fleet(*, domain_key: str, fleet: Optional[Mapping[str, Any]]) -> str:
    """Fleet 档的判定，单独成函数给「按 fleet_ref 直接查」的调用方用。

    工单指派人校验手里只有 ``fleet_ref``，没有一条完整的 ``source`` 可解析。让它
    拼一个假 source 去走 :func:`verdict` 是可行的，但那样「判定」就被藏在一次
    字符串往返里；单独一个入口，两边共用同一份规则，谁也不用假装有 post_id。
    """
    if fleet is None:
        return "unregistered"
    if fleet.get("revoked"):
        return "revoked"
    domains = fleet.get("domains") or []
    if (domain_key or "").strip() not in domains:
        return "domain_mismatch"
    return "ok"


def verdict(
    source: Optional[str],
    *,
    domain_key: str,
    via: str,
    fleet: Optional[Mapping[str, Any]] = None,
    agent_is_member: Optional[bool] = None,
    authenticated_as: Optional[str] = None,
) -> str:
    """判定一条提交来源在其目标域上是否可被接受。

    ``fleet`` 传登记行投影（``{"domains": [...], "revoked": bool}``），``None``
    表示查无登记。``agent_is_member`` 为该身份是否仍是目标域的活跃成员。
    ``authenticated_as`` 是本次请求已认证的身份——``agent:`` 与 ``user:`` 两类
    的信任依据都是它：**你只能以自己的身份提交**。``None`` 表示调用方没有身份可
    比，此时这两类一律判为不匹配（证不出来就不算数）。

    调用方**必须**把 ``via`` 说对：``extract:`` 的放行只依赖它。传错的后果不是
    「校验变宽松」，而是「校验消失」——所以两个调用点各传自己的常量，不共享。
    """
    prefix, parts, malformed = classify_source(source)

    if prefix is None:
        return "unknown_prefix"
    if malformed or parts is None:
        return "malformed"

    if prefix == PREFIX_EXTRACT:
        return "ok" if via == VIA_IN_PROCESS else "pipeline_impersonation"

    if prefix == PREFIX_AGENT:
        if parts["domain"] != (domain_key or "").strip():
            return "agent_domain_mismatch"
        if not agent_is_member:
            return "agent_not_member"
        # A minted identity may only submit as itself.
        if (authenticated_as or "").strip() not in ("", (source or "").strip()):
            return "agent_not_member"
        return "ok"

    if prefix == PREFIX_USER:
        if (authenticated_as or "").strip() != parts["identity"]:
            return "user_mismatch"
        return "ok"

    return verdict_for_fleet(domain_key=domain_key, fleet=fleet)


def is_allowed(result: str) -> bool:
    """结论是否放行。只有 ``ok`` 放行；宽松迁移档由调用方另行处理。"""
    return result == "ok"


def may_submit_as_source(source: Any, *, fleet_ref: str) -> bool:
    """``fleet:<自己的 fleet_ref>/<post>`` —— 机器面**提产物**的归属判据。

    与 :func:`may_read_runner_ref` 是同一条前缀规则，但两个名字必须分开：一个
    判「读自己那一轮的回执」，一个判「以自己身份提产物」。将来收紧其中之一
    （例如提交额外要求该工单已被自己认领）时，共用一个名字会让收紧在另一处
    静默生效。域匹配由调用方保证——``_authenticate_consumer`` 先判过绑定域。
    """
    return may_read_runner_ref(source, fleet_ref=fleet_ref)


def may_read_runner_ref(
    runner_ref: Any,
    *,
    fleet_ref: Optional[str] = None,
    is_member: bool = False,
    is_admin: bool = False,
) -> bool:
    """谁能读到某次外部回写——运行台账的隔离判据。

    三种读者，三种依据：

    - **平台管理员**：全读（迁移与排障要能核对）。
    - **机器消费者**（``fleet_ref`` 非空，且该登记是 ``fleet`` 种类）：只能读
      ``fleet:<自己的 fleet_ref>/`` 开头的运行。它读的是**自己那一轮的落库回
      执**，所以「按前缀判」就够了；反查到别人的轮次对自检没有用处，对有泄漏
      就有。
    - **人（域成员）**：域成员在团队区本来就能看到整份台账，读面不该比页面更严
      或更松——同一条判据，两种入口。

    证不出来的一律不读（``False``）：``runner_ref`` 为空而调用方又既非管理员也
    非成员时，那里没有东西可以证明归属。
    """
    if is_admin:
        return True
    ref = (runner_ref or "").strip()
    if fleet_ref:
        fleet = (fleet_ref or "").strip()
        if not fleet:
            return False
        return ref.startswith(f"{PREFIX_FLEET}{fleet}/")
    return bool(is_member)
