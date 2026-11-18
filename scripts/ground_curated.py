"""人工提议 + 机器验收的接地：只写「概念名确实出现在该条文正文里」的那些。

    python3 scripts/ground_curated.py --dry-run
    python3 scripts/ground_curated.py

为什么要有这一层：`ground_from_starter.py` 接的是起始集里已登记的出处；这里接的是
**新补的**出处。补出处本身是判断（哪一条才是这个概念的依据），但写进去之前可以做
一次确定性验收——被引条文里是否真的出现了这个概念名。

- 验收通过 → 写入 `defines`，`attrs.via = "curated-verified"`，并记下命中片段；
- 验收不通过 → 不写，并把原因报出来（引文与条文对不上就说明提议错了）。

这样"人工策展"和"可核验"不冲突：人负责选条文，机器负责确认这条文里真有它。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import packs.legal  # noqa: E402,F401
from packs.legal.entity_keys import parse_citation  # noqa: E402

#: 提议（概念 → 出处）。每条都会先过"条文里是否出现概念名"的验收。
PROPOSALS: list[tuple[str, str]] = [
    ("故意杀人", "《中华人民共和国刑法》第二百三十二条"),
    ("死刑", "《中华人民共和国刑法》第四十八条"),
    ("死刑缓期二年执行", "《中华人民共和国刑法》第五十条"),
    ("犯罪情节", "《中华人民共和国刑法》第六十一条"),
    ("国家工作人员", "《中华人民共和国刑法》第九十三条"),
    ("为他人谋取利益", "《中华人民共和国刑法》第三百八十五条"),
    ("违约", "《中华人民共和国民法典》第五百七十七条"),
    ("房屋买卖居间合同", "《中华人民共和国民法典》第九百六十一条"),
]


def verify(conn, *, domain_key: str, concept: str, ref: str) -> dict:
    """解析出处 → 取条款正文 → 看概念名是否逐字出现。"""
    from src.bench import authoring, keys

    parsed = parse_citation(ref)
    if not parsed:
        return {"concept": concept, "ref": ref, "ok": False, "reason": "出处无法解析"}
    doc, number = parsed
    clause_key = keys.clause_key(doc, number)
    live = authoring.authoring_live_key_kinds(conn, domain_key=domain_key)
    if clause_key not in live:
        return {"concept": concept, "ref": ref, "clause": clause_key, "ok": False,
                "reason": "该条款尚未取入本体"}
    unit = authoring.authoring_get_unit(
        conn, domain_key=domain_key, kind=live[clause_key], external_key=clause_key)
    body = (unit or {}).get("body") or ""
    hit = concept in body
    return {"concept": concept, "ref": ref, "clause": clause_key, "ok": hit,
            "reason": None if hit else "条文正文里没有出现该概念名",
            "snippet": body[max(0, body.find(concept) - 20): body.find(concept) + len(concept) + 20].strip()
            if hit else ""}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default="legal")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.bench import authoring
    from src.eval.db import connect

    conn = connect()
    try:
        results = [verify(conn, domain_key=args.domain, concept=c, ref=r)
                   for c, r in PROPOSALS]
        ok = [r for r in results if r["ok"]]
        bad = [r for r in results if not r["ok"]]
        print(f"提议 {len(results)}，验收通过 {len(ok)}，不通过 {len(bad)}")
        for r in ok:
            print(f"  通过 {r['concept']:<14} → {r['clause']:<18} {r['snippet'][:40]}")
        for r in bad:
            print(f"  拒绝 {r['concept']:<14} {r['reason']}")
        if args.dry_run:
            print("[dry-run] nothing written")
            return 0
        created = 0
        for r in ok:
            authoring.authoring_create_relationship(
                conn, domain_key=args.domain, kind="defines",
                from_key=r["concept"], to_key=r["clause"],
                body=f"{r['concept']} defines {r['clause']}",
                operator="ground-curated",
                attrs={"via": "curated-verified", "citation": r["ref"],
                       "matched_text": r["snippet"]},
            )
            created += 1
        print(f"写入 defines：{created}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
