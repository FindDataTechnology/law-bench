"""确定性接地：把概念挂到**正文里逐字出现它**的条款上。

为什么不用模型：`defines` 的意思是"这条概念在文档里有出处"，而"这一条正文里出现了
这个名字"是**可以用字符串核对的**。让模型判断"这条条款是否定义了这个概念"会引入
判断，而我们只需要一个可复核的锚点。

三条纪律：

- **一条概念最多接一条关系**：接地率要的是"有没有落点"，不是"挂了多少条"；
  多挂会在图上制造一堆噪声边，反而看不出结构。
- **同一部法只取最短的那条**：同一概念在多条里出现时，条号最小/正文最短的通常
  就是定义句本身（长条文多为列举或引用）。
- **匹配是逐字的**：概念名必须在条款正文里原样出现；不做同义、不做过干（stemming）；
- **泛称不自动接地**：一个名字在过多条款里出现（十几个候选），说明它是通用词而不是
  某个条文定义的对象。硬挑一条只会造出一条看似有据、实则任意的边。这类留给人工，
  并在报告里点名（``too_generic``）。

产出走 `authoring_create_relationship`（内核唯一写路径），因此词表与事件都在。
"""

from __future__ import annotations

from typing import Any, Optional

from . import authoring, keys


def _load(conn: Any, *, domain_key: str) -> tuple[list[dict], list[dict], set[str]]:
    """(概念, 条款, 已有 defines 的起点集合)。"""
    concepts = [
        dict(r) for r in conn.execute(
            "SELECT external_key, body FROM knowledge_units "
            "WHERE namespace = %s AND kind = 'concept' AND (tags->>'deleted') IS NULL "
            "ORDER BY external_key",
            (domain_key,),
        ).fetchall()
    ]
    clauses = [
        dict(r) for r in conn.execute(
            "SELECT external_key, body, attrs FROM knowledge_units "
            "WHERE namespace = %s AND kind = 'clause' AND (tags->>'deleted') IS NULL",
            (domain_key,),
        ).fetchall()
    ]
    grounded = set()
    for row in conn.execute(
        "SELECT external_key FROM knowledge_units "
        "WHERE namespace = %s AND kind = 'defines' AND (tags->>'deleted') IS NULL",
        (domain_key,),
    ).fetchall():
        frm, _, _rest = (row["external_key"] or "").partition("->")
        grounded.add(frm)
    return concepts, clauses, grounded


def plan(
    conn: Any, *, domain_key: str, limit: Optional[int] = None,
    max_candidates: int = 3,
) -> dict:
    """算出「哪条概念挂到哪条条款」，不改任何东西。"""
    concepts, clauses, grounded = _load(conn, domain_key=domain_key)
    todo = [c for c in concepts if c["external_key"] not in grounded]
    picks: list[dict] = []
    too_generic: list[dict] = []
    for concept in todo:
        name = concept["external_key"]
        if not name:
            continue
        hits = [
            cl for cl in clauses
            if name in (cl.get("body") or "")
        ]
        if not hits:
            continue
        if len(hits) > max_candidates:
            # 泛称：出现在太多条款里，没有唯一定义条。硬挑一条=造一条任意的边。
            too_generic.append({"concept": name, "candidates": len(hits)})
            continue
        # 同一条文里出现多次只算一次；取最短正文（多为定义句本身），再按条号兜底
        best = sorted(
            hits,
            key=lambda cl: (len(cl.get("body") or ""), cl["external_key"]),
        )[0]
        snippet_at = (best.get("body") or "").find(name)
        picks.append({
            "concept": name,
            "clause": best["external_key"],
            "snippet": (best.get("body") or "")[max(0, snippet_at - 20): snippet_at + len(name) + 20],
            "candidates": len(hits),
        })
    if limit:
        picks = picks[: int(limit)]
    return {
        "domain": domain_key,
        "concepts": len(concepts),
        "already_grounded": len(concepts) - len(todo),
        "ungrounded": len(todo),
        "groundable": len([p for p in picks]),
        "no_clause_mentions": len(todo) - len({p['concept'] for p in picks})
                             - len({g['concept'] for g in too_generic}),
        "too_generic": too_generic,
        "picks": picks,
    }


def ground_concepts(
    conn: Any, *, domain_key: str, dry_run: bool = True, limit: Optional[int] = None
) -> dict:
    """把 plan() 的结论落成 `defines` 关系（幂等：已有接地的概念不再接）。"""
    planned = plan(conn, domain_key=domain_key, limit=limit)
    if dry_run:
        return {**planned, "dry_run": True, "created": 0}

    created = 0
    for pick in planned["picks"]:
        try:
            authoring.authoring_create_relationship(
                conn, domain_key=domain_key, kind="defines",
                from_key=pick["concept"], to_key=pick["clause"],
                body=f"{pick['concept']} defines {pick['clause']}",
                operator="ground-concepts",
                attrs={"matched_text": pick["snippet"],
                       "candidates": pick["candidates"],
                       "via": "deterministic-mention"},
            )
        except ValueError:
            # 词表/端点不合法就跳过这一条，不中断整批：接地是增量改善，不是事务。
            continue
        created += 1
    return {**planned, "dry_run": False, "created": created}


def after(conn: Any, *, domain_key: str) -> dict:
    """接完再看一次：接地率 + 仍然悬空的概念清单。"""
    concepts, _clauses, grounded = _load(conn, domain_key=domain_key)
    ungrounded = [c["external_key"] for c in concepts if c["external_key"] not in grounded]
    return {
        "concepts": len(concepts),
        "grounded": len(concepts) - len(ungrounded),
        "ratio": round((len(concepts) - len(ungrounded)) / len(concepts), 4) if concepts else None,
        "ungrounded": ungrounded,
    }
