"""Successor mapping seed: 死法 → 承继法 (remediate-repealed-citations).

Explicit pairs are resolved against the catalog replica by exact normalized
title (law ids are stable but titles are the human-auditable key). Any dead
law cited by clauses but absent from the explicit map (local regulations
without a confirmed successor) becomes a ``needs_human`` placeholder that the
apply step never uses.
"""

from __future__ import annotations

from src.eval.db import connect, now_iso

from .resolve import normalize_name
from .store import ensure_schema

# rule civilcode-2021: 民法典施行即承继六法（authority = 民法典第1260条废止清单）
_CIVILCODE = "civilcode-2021"
_EFFECTIVE_2021 = "2021-01-01"

EXPLICIT_MAP: list[dict] = [
    # civilcode succession
    {"dead": "中华人民共和国合同法", "successor": "中华人民共和国民法典",
     "authority": "中华人民共和国民法典", "effective": _EFFECTIVE_2021, "rule": _CIVILCODE},
    {"dead": "中华人民共和国物权法", "successor": "中华人民共和国民法典",
     "authority": "中华人民共和国民法典", "effective": _EFFECTIVE_2021, "rule": _CIVILCODE},
    {"dead": "中华人民共和国民法总则", "successor": "中华人民共和国民法典",
     "authority": "中华人民共和国民法典", "effective": _EFFECTIVE_2021, "rule": _CIVILCODE},
    {"dead": "中华人民共和国民法通则", "successor": "中华人民共和国民法典",
     "authority": "中华人民共和国民法典", "effective": _EFFECTIVE_2021, "rule": _CIVILCODE},
    {"dead": "中华人民共和国担保法", "successor": "中华人民共和国民法典",
     "authority": "中华人民共和国民法典", "effective": _EFFECTIVE_2021, "rule": _CIVILCODE},
    {"dead": "中华人民共和国侵权责任法", "successor": "中华人民共和国民法典",
     "authority": "中华人民共和国民法典", "effective": _EFFECTIVE_2021, "rule": _CIVILCODE},
    # 2020 司法解释清理：建工解释（二）并入（一）
    {"dead": "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释（二）",
     "successor": "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释（一）",
     "authority": None, "effective": "2021-01-01", "rule": "merge-2020"},
    # 部门规章更替
    {"dead": "网络交易管理办法", "successor": "网络交易监督管理办法",
     "authority": None, "effective": "2021-05-01", "rule": "replace-2021"},
    # 地方条例更替（r3，人工判定 2026-09-26）
    {"dead": "天津市旅游条例", "successor": "天津市旅游促进条例",
     "authority": "天津市旅游促进条例", "effective": "2022-09-01", "rule": "local-replace-2022"},
]


def _laws_by_norm(conn) -> dict[str, dict]:
    return {
        normalize_name(r["title"]): dict(r)
        for r in conn.execute("SELECT id, title, status FROM law_catalog.laws").fetchall()
    }


def seed_successor_map(db=None) -> dict:
    """(Re-)seed the successor map. Returns a summary dict.

    Explicit pairs upsert resolved ids (dead side must resolve; a dead title
    that no longer exists is reported and skipped). Dead laws cited by
    clauses but not covered become needs_human placeholders. Existing rows
    are refreshed, never silently deleted — dropping a mapping is a manual
    act.
    """
    conn = connect(db)
    try:
        ensure_schema(conn)
        by_norm = _laws_by_norm(conn)
        now = now_iso()
        seeded, skipped = [], []
        for entry in EXPLICIT_MAP:
            dead = by_norm.get(normalize_name(entry["dead"]))
            succ = by_norm.get(normalize_name(entry["successor"]))
            auth = by_norm.get(normalize_name(entry["authority"])) if entry["authority"] else None
            if dead is None:
                skipped.append({"dead": entry["dead"], "reason": "dead title not in catalog"})
                continue
            if succ is None or (succ["status"] not in ("有效", "已修改")):
                skipped.append({"dead": entry["dead"], "reason": f"successor unresolved/invalid: {entry['successor']}"})
                continue
            conn.execute(
                "INSERT INTO law_catalog.successor_map "
                "(dead_law_id, successor_law_id, authority_law_id, effective_date, "
                " rule_version, needs_human, seeded_at) VALUES (%s,%s,%s,%s,%s,false,%s) "
                "ON CONFLICT (dead_law_id) DO UPDATE SET successor_law_id=EXCLUDED.successor_law_id, "
                "authority_law_id=EXCLUDED.authority_law_id, effective_date=EXCLUDED.effective_date, "
                "rule_version=EXCLUDED.rule_version, needs_human=false, seeded_at=EXCLUDED.seeded_at",
                (dead["id"], succ["id"], auth["id"] if auth else None,
                 entry["effective"], entry["rule"], now),
            )
            seeded.append({"dead": dead["title"], "dead_id": dead["id"], "successor_id": succ["id"]})

        # placeholders: dead laws cited by clauses, unmapped
        placeholders = conn.execute(
            "INSERT INTO law_catalog.successor_map (dead_law_id, successor_law_id, "
            "authority_law_id, effective_date, rule_version, needs_human, seeded_at) "
            "SELECT DISTINCT l.id, NULL::bigint, NULL::bigint, NULL::text, 'manual-pending', true, %s "
            "FROM law_catalog.clause_law_refs r "
            "JOIN law_catalog.laws l ON l.id = r.law_id "
            "WHERE l.status IN ('已废止','失效','已失效') "
            "AND l.id NOT IN (SELECT dead_law_id FROM law_catalog.successor_map) "
            "RETURNING dead_law_id",
            (now,),
        ).fetchall()
        conn.commit()
        return {"seeded": seeded, "skipped": skipped,
                "placeholders": [p["dead_law_id"] for p in placeholders]}
    finally:
        conn.close()
