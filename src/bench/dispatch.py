"""Batch dispatch: turn estate gaps into assigned tasks (§4.7).

The estate matrix answers "what is missing where". The next operator action is
"give this to someone", and doing that by hand for a dozen dead sub-domains is
exactly the kind of chore that stops a domain tree from being maintained.

Two rules shape this module:

- **Confirmation is a separate page, and loading the estate writes nothing.** A
  batch that creates N tasks as a side effect of rendering a filtered list would
  be one accidental refresh away from N duplicates.
- **A gap that already has an open task is not dispatched again.** The check is
  on the task's ``target_key`` (the pillar) so repeated confirmations converge
  instead of piling up. "Already assigned" is reported, not silently skipped.

Nothing here decides *who*: the caller passes an assignee string (a person or a
fleet). Filling in a default owner would be a policy this module has no basis
for.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from . import authoring, estate

#: Where each gap goes. **The** routing table — ``team_roles.GAP_OWNER`` is
#: derived from it, so the two can never disagree about who owns a gap.
#:
#: ``kernel:<role>`` — a deterministic in-process role does it (no judgement
#: needed, and the result is mechanically checkable).
#: ``fleet``         — needs judgement / an LLM, so it becomes a work order a
#: registered fleet claims at its own cadence.
#: ``human``         — neither: review backlog is a person's queue. Dispatching
#: it to an agent would only move the backlog somewhere less visible.
#:
#: Written as data rather than inside a prompt: a rule the model is asked to
#: follow is a probability; a table is a constraint.
GAP_ROUTE: dict[str, str] = {
    "ontology": "kernel:builder",
    "knowledge": "kernel:scout",
    "eval": "kernel:eval",
    "quality:grounding": "kernel:concept",
    "quality:evidence": "kernel:builder",
    "quality:referential": "kernel:verifier",
    "quality:key_hygiene": "kernel:builder",
    "quality:review_lag": "human",
    # 模板改进需要判断（添哪些类型、挂哪些尺子），确定性内核岗位做不了。
    # 这是 FLEET_ROUTE 第一次真的被用上：此前它只是词汇表里一个常量。
    "quality:template": "fleet",
}

#: Route prefix for "an in-process deterministic role owns this".
KERNEL_PREFIX = "kernel:"

#: Route marker for "a person owns this".
HUMAN_ROUTE = "human"

#: Route marker for "a registered fleet owns this" (kept for the vocabulary even
#: though every current gap happens to be kernel- or human-owned).
FLEET_ROUTE = "fleet"

#: Pillar → what the assignee is being asked to do. Kept next to the gap
#: vocabulary (``estate.PILLARS``) so a new pillar cannot be dispatched with a
#: blank title.
GAP_TASKS: dict[str, dict[str, str]] = {
    "knowledge": {
        "title": "补语料：让本域有可检索内容",
        "detail": "缺口＝本域当前检索不到任何内容块。二选一：①在「知识库」区订阅已有库的源；"
                  "②若是新语料，先在 admin「语料库登记」建库/加源，再回来订阅。"
                  "验收：知识库区显示块数 > 0，全域名录该域的语料缺口消失。",
    },
    "ontology": {
        "title": "补本体：本域还没有已整理的知识单元",
        "detail": "缺口＝本域没有自己的知识单元（继承来的不算）。按模板声明的实体类型/关系类型"
                  "整理实体与关系，落库到本域路径。验收：本体区出现本域单元，缺口消失。",
    },
    "eval": {
        "title": "补评测标准：本域还没有可生效的 rubric",
        "detail": "缺口＝本域沿父链取不到任何 rubric。二选一：①继承父域标准（无需操作，订阅即生效）；"
                  "②新建本域标准；③偏离父域口径必须 fork 并写明差异。验收：评测标准区非空，缺口消失。",
    },
    # 质量缺口：四柱不空但内容立不住。与"补本体/补语料/补评测"并列，但目标不同：
    # 前者是把空缺填上，后者是把比率拉回阈值。
    "quality:grounding": {
        "title": "提接地：让概念挂到条款上",
        "detail": "缺口＝概念中带定义关系的比例低于阈值。做法：从已取入的条款出发，"
                  "为概念补 defines 关系（关系端点须已存在）。验收：接地率回到阈值以上。",
    },
    "quality:evidence": {
        "title": "补依据：给没有出处的单位补可回源依据",
        "detail": "缺口＝单位缺少 attrs.evidence 或 attrs.chunk_id。做法：按类型定位缺口"
                  "（机关/关系/概念常缺），从语料逐字取文补上。验收：证据率回到阈值以上。",
    },
    "quality:referential": {
        "title": "修悬空关系：两端必须都在活单位上",
        "detail": "缺口＝关系的一端指向已退或不存在的单位。做法：退文档时同批退关系，"
                  "或补回被指向的单位。验收：参照完整率回到 1.0。",
    },
    "quality:key_hygiene": {
        "title": "归名存量键：还能归名的键应当已归名",
        "detail": "缺口＝库里仍有未归名形态的键（历史数据）。做法：按该域规则归名并记 "
                  "aliases，合并同实体。验收：仍可归名的键数为 0。",
    },
    "quality:review_lag": {
        "title": "清复核积压：提案等待超过阈值",
        "detail": "缺口＝待确认提案最老一条超过阈值。做法：按批复核（不是逐条），"
                  "先在批次里看共同主张与差异清单。验收：最老待确认年龄回到阈值以内。",
    },
    "quality:template": {
        "title": "给模板挂尺子：该域锚定模板无法被评测",
        "detail": "缺口＝锚定模板的 rubric_refs 为空或声明的尺子解析不到。后果不是一个坏分数，"
                  "而是永远算不出这个域有没有变差。做法：为该模板补上可用的 rubric 引用"
                  "（或补建 rubric 后引用），再保存新版本。验收：质量视图的模板可评性由"
                  "「不可评」变为一个比率，缺口消失。",
    },
}


def dispatchable(rows: Iterable[dict], gap: str) -> list[dict]:
    """Rows missing ``gap``, with the reason a task would carry."""
    if gap not in GAP_TASKS:
        raise ValueError(f"unknown pillar {gap!r}; expected one of {sorted(GAP_TASKS)}")
    return [r for r in rows if gap in r["gaps"]]


def open_targets(conn: Any, *, domain_id: int, target_kind: str = "estate-gap") -> set[str]:
    """Pillars this domain already has an *open* task for."""
    rows = conn.execute(
        "SELECT target_key FROM authoring_tasks "
        "WHERE domain_id = %s AND target_kind = %s AND status IN ('pending','in_progress')",
        (domain_id, target_kind),
    ).fetchall()
    return {r["target_key"] for r in rows if r["target_key"]}


def route_for(gap: str) -> str:
    """Who owns ``gap``: ``kernel:<role>``, ``fleet`` or ``human``.

    Unknown gaps are refused rather than defaulting to a route — a silent
    default would let a new pillar be dispatched to the wrong kind of owner and
    nobody would notice until the work did not happen.
    """
    if gap not in GAP_TASKS:
        raise ValueError(f"unknown pillar {gap!r}; expected one of {sorted(GAP_TASKS)}")
    try:
        return GAP_ROUTE[gap]
    except KeyError:  # a pillar exists without a route — refuse, do not guess
        raise ValueError(
            f"pillar {gap!r} has no route; add it to GAP_ROUTE"
        ) from None


def kernel_role_for(gap: str) -> Optional[str]:
    """The in-process role that owns ``gap``, or ``None`` when it is not a kernel gap."""
    route = route_for(gap)
    if route.startswith(KERNEL_PREFIX):
        return route[len(KERNEL_PREFIX):]
    return None


def plan(
    conn: Any,
    *,
    rows: Iterable[dict],
    gap: str,
    assignee: str,
    assignee_kind: Optional[str] = None,
    assignee_ref: Optional[str] = None,
) -> dict:
    """What a confirmation would do — computed without writing anything."""
    targets = dispatchable(rows, gap)
    will: list[dict] = []
    already: list[dict] = []
    for row in targets:
        domain = row["domain"]
        if gap in open_targets(conn, domain_id=domain["id"]):
            already.append(domain)
            continue
        will.append(domain)
    return {
        "gap": gap,
        "assignee": (assignee or "").strip(),
        "assignee_kind": assignee_kind or "human",
        "assignee_ref": assignee_ref,
        "route": route_for(gap),
        "pillar": GAP_TASKS[gap],
        "will_create": will,
        "already_open": already,
    }


def dispatch(
    conn: Any,
    *,
    rows: Iterable[dict],
    gap: str,
    assignee: str,
    created_by: str,
    assignee_kind: str = "human",
    assignee_ref: Optional[str] = None,
) -> dict:
    """Create one task per domain still missing ``gap`` (idempotent per pillar).

    ``assignee`` is the human-readable label; ``assignee_kind``/``assignee_ref``
    say which of the three kinds it is and carry the reference authorization
    reads. When ``assignee_kind`` is ``kernel-role`` the route table is the
    authority: the caller may pick a person or a fleet, but it must not hand a
    kernel-owned gap to someone the table never assigned it to.
    """
    assignee = (assignee or "").strip()
    if not assignee:
        raise ValueError("assignee is required")
    route = route_for(gap)
    kernel_role = kernel_role_for(gap)
    if kernel_role is not None and assignee_kind == "kernel-role":
        if (assignee_ref or assignee) != kernel_role:
            raise ValueError(
                f"缺口 {gap!r} 由内核岗位 {kernel_role!r} 负责，不能派给 {assignee_ref or assignee!r}"
            )

    planned = plan(
        conn, rows=rows, gap=gap, assignee=assignee,
        assignee_kind=assignee_kind, assignee_ref=assignee_ref,
    )
    created: list[dict] = []
    for domain in planned["will_create"]:
        created.append(
            authoring.authoring_create_task(
                conn,
                domain_id=domain["id"],
                assignee=assignee,
                title=planned["pillar"]["title"],
                detail=planned["pillar"]["detail"],
                target_kind="estate-gap",
                target_key=gap,
                created_by=created_by,
                assignee_kind=assignee_kind,
                assignee_ref=assignee_ref,
            )
        )
    return {
        "gap": gap,
        "assignee": assignee,
        "assignee_kind": assignee_kind,
        "assignee_ref": assignee_ref,
        "route": route,
        "created": created,
        "already_open": planned["already_open"],
    }


def rows_for_gap(conn: Any, *, domains: list[dict], gap: str) -> list[dict]:
    """Estate rows for the given domains (one network-free read per domain).

    ``estate.matrix`` is the single source of truth for what counts as a gap, so
    dispatch cannot disagree with the page that motivated it.
    """
    if gap not in GAP_TASKS:
        raise ValueError(f"unknown pillar {gap!r}; expected one of {sorted(GAP_TASKS)}")
    return estate.matrix(conn, domains=domains)
