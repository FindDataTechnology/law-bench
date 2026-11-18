"""把起始概念集里**人工读过原文**的出处，接成本体的 defines 关系。

    python3 scripts/ground_from_starter.py --dry-run
    python3 scripts/ground_from_starter.py

为什么这一步是正当的：`packs/legal/starters/concepts-v1.json` 里每个概念都带
``attrs.statute_refs``（如「《中华人民共和国合同法》第四百二十四条」），那是人读原文
时留下的溯源，不是模型猜的。它一直躺在 pack 里没被接上——所以概念悬空不是缺判据，
而是**缺这一步搬运**。

两条硬纪律：

- 只接**条款已经在本体里**的：出处指向一条还没取入的条款时不造端点，记为 unresolved；
- 一条概念只接一条：接地率要的是"有没有落点"，多挂会让图变噪声；优先取第一条能解出的。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import packs.legal  # noqa: E402,F401  （注册归名规则）
from packs.legal.entity_keys import parse_citation  # noqa: E402

STARTER = Path(__file__).resolve().parent.parent / "packs" / "legal" / "starters" / "concepts-v1.json"


def _load_units() -> list[dict]:
    data = json.loads(STARTER.read_text(encoding="utf-8"))
    return data.get("units") or []


def plan(conn, *, domain_key: str) -> dict:
    """算出「哪条概念接哪条条款」；不写任何东西。"""
    from src.bench import authoring, keys

    live = authoring.authoring_live_key_kinds(conn, domain_key=domain_key)
    grounded = set()
    for row in conn.execute(
        "SELECT external_key FROM knowledge_units WHERE namespace = %s "
        "AND kind = 'defines' AND (tags->>'deleted') IS NULL",
        (domain_key,),
    ).fetchall():
        grounded.add((row["external_key"] or "").partition("->")[0])

    picks, unresolved, already = [], [], []
    for unit in _load_units():
        concept = unit.get("external_key")
        if not concept:
            continue
        # 起始集里除了概念还有法规单位（合同法/公司法/…），它们是 defines 的**端点**
        # 而不是要接地的对象。把它们当概念报"待补出处"是错分类（实测 4 条）。
        if (unit.get("kind") or "concept") != "concept":
            continue
        if concept in grounded:
            already.append(concept)
            continue
        if concept not in live:
            unresolved.append({"concept": concept, "reason": "概念不在本体中"})
            continue
        refs = (unit.get("attrs") or {}).get("statute_refs") or []
        if not refs:
            # 三种失败原因必须分开报：「没登记出处」「出处指向上游还没取入的条款」
            # 「概念不在本体」是三件不同的事，合成一句话就会把人引到错误的修法上
            # （实测：合同解除/违约责任 报的是"条款未取入"，实际是起始集没登记出处）。
            unresolved.append({"concept": concept, "reason": "起始集未登记出处"})
            continue
        hit = None
        for ref in refs:
            parsed = parse_citation(ref)
            if not parsed:
                continue
            doc, number = parsed
            cl = keys.clause_key(doc, number)
            if cl in live:
                hit = {"concept": concept, "clause": cl, "ref": ref}
                break
        if hit:
            picks.append(hit)
        else:
            unresolved.append({"concept": concept, "refs": refs,
                               "reason": "出处所指条款尚未取入本体"})
    return {"concepts_with_refs": len(_load_units()), "already_grounded": len(already),
            "picks": picks, "unresolved": unresolved}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default="legal")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.bench import authoring
    from src.eval.db import connect

    conn = connect()
    try:
        out = plan(conn, domain_key=args.domain)
        print(f"起始集概念：{out['concepts_with_refs']}，其中已接地 {out['already_grounded']}")
        print(f"可接：{len(out['picks'])}")
        for p in out["picks"]:
            print(f"  {p['concept']:<16} → {p['clause']:<22} （{p['ref']}）")
        if out["unresolved"]:
            print(f"待补：{len(out['unresolved'])}")
            for u in out["unresolved"][:6]:
                print(f"  - {u['concept']}：{u['reason']}")
        if args.dry_run:
            print("[dry-run] nothing written")
            return 0

        created = 0
        for p in out["picks"]:
            authoring.authoring_create_relationship(
                conn, domain_key=args.domain, kind="defines",
                from_key=p["concept"], to_key=p["clause"],
                body=f"{p['concept']} defines {p['clause']}",
                operator="ground-from-starter",
                attrs={"via": "starter-curated", "citation": p["ref"]},
            )
            created += 1
        print(f"写入 defines：{created}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
