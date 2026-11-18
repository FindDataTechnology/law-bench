"""把政务概念接到承载它的公文上（defines），让 `grounding` 从 None 变可量。

    python3 scripts/ground_gov_concepts.py --dry-run
    python3 scripts/ground_gov_concepts.py

为什么要有这一步：概念进本体只是"有实体"，接地率算的是"有没有依据"。政务线的
`defines` 方向固定 **概念 → 公文**（该公文是这条概念的依据），与法律线同向，
这样 `quality.grounding` 两条线读法一致。

依据不是猜的：每条概念都带抽取时的 `evidence`（`chunk_id` + 逐字 `quote`）。本脚本
按 chunk 找到它所属的 corpus 文档，再映射到本体的文档单位——映射不上就不写，并
报出来，而不是拿"最近一条文档"凑数。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _doc_units_by_corpus_id(conn) -> dict[str, str]:
    """corpus 文档号 → 本体里的文档单位键。"""
    out: dict[str, str] = {}
    for row in conn.execute(
        "SELECT external_key, attrs FROM knowledge_units "
        "WHERE namespace = 'gov' AND kind = 'document' AND (tags->>'deleted') IS NULL"
    ).fetchall():
        doc_id = ((row["attrs"] or {}).get("corpus") or {}).get("doc_id")
        if doc_id:
            out[str(doc_id)] = row["external_key"]
    return out


def _chunk_document(conn, *, chunk_id: str) -> str | None:
    """chunk → 它所属的 corpus 文档号（外部库，只读）。"""
    import psycopg

    from src.bench import libraries

    lib = libraries.get_library(conn, library_key="text-library")
    # resolve_location 已经把 env 变量名换成连接串；缺变量时它自己会指名报错，
    # 所以这里不要再拼一次（拼错就会把连接串当变量名，并把明文打进日志）。
    dsn = libraries.resolve_location(lib)["dsn_env"]
    if not str(chunk_id).isdigit():
        return None
    with psycopg.connect(dsn, connect_timeout=10) as ext:
        row = ext.execute(
            "SELECT document_id FROM corpus_chunks_gov WHERE id = %s", (int(chunk_id),)
        ).fetchone()
    return str(row[0]) if row else None


def plan(conn) -> dict:
    """算出「哪条概念接到哪份公文」；不写任何东西。"""
    docs = _doc_units_by_corpus_id(conn)
    concepts = {
        r["external_key"]: r["attrs"] or {}
        for r in conn.execute(
            "SELECT external_key, attrs FROM knowledge_units "
            "WHERE namespace = 'gov' AND kind = 'concept' AND (tags->>'deleted') IS NULL"
        ).fetchall()
    }
    # The evidence (chunk_id/quote) lives on the proposal that introduced the
    # concept, not on the unit: the kernel write path stores only the claim.
    # Reading it back from the proposal is what keeps provenance honest — the
    # alternative is guessing a document from "the most recent one".
    evidence_by_key = {
        r["external_key"]: (r["evidence"] or {})
        for r in conn.execute(
            "SELECT external_key, evidence FROM domain_proposals "
            "WHERE domain_id = (SELECT id FROM domains WHERE key = 'gov') "
            "AND state = 'confirmed' AND evidence IS NOT NULL "
            "ORDER BY id"
        ).fetchall()
    }
    grounded = {
        (r["external_key"] or "").partition("->")[0]
        for r in conn.execute(
            "SELECT external_key FROM knowledge_units "
            "WHERE namespace = 'gov' AND kind = 'defines' AND (tags->>'deleted') IS NULL"
        ).fetchall()
    }
    picks, unresolved = [], []
    for concept, attrs in sorted(concepts.items()):
        if concept in grounded:
            continue
        ev = evidence_by_key.get(concept) or {}
        chunk_id = attrs.get("chunk_id") or ev.get("chunk_id")
        if not chunk_id:
            unresolved.append({"concept": concept, "reason": "没有 evidence.chunk_id，无法定位依据"})
            continue
        doc_id = _chunk_document(conn, chunk_id=str(chunk_id))
        if not doc_id:
            unresolved.append({"concept": concept, "reason": f"chunk {chunk_id} 取不到所属文档"})
            continue
        doc_key = docs.get(doc_id)
        if not doc_key:
            unresolved.append({"concept": concept,
                               "reason": f"chunk {chunk_id} 所属文档（corpus id={doc_id}）尚未取入本体"})
            continue
        picks.append({"concept": concept, "document": doc_key, "chunk_id": str(chunk_id),
                      "quote": attrs.get("quote") or ev.get("quote")})
    return {"concepts": len(concepts), "already_grounded": len(concepts) - len(picks) - len(unresolved),
            "picks": picks, "unresolved": unresolved}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--domain", default="gov")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.bench import authoring
    from src.eval.db import connect

    conn = connect()
    try:
        out = plan(conn)
        print(f"概念 {out['concepts']}，已接地 {out['already_grounded']}，可接 {len(out['picks'])}")
        for p in out["picks"]:
            print(f"  {p['concept']:<12} → {p['document'][:40]}（chunk {p['chunk_id']}）")
        for u in out["unresolved"]:
            print(f"  待补 {u['concept']}：{u['reason']}")
        if args.dry_run:
            print("[dry-run] nothing written")
            return 0

        created = 0
        for p in out["picks"]:
            authoring.authoring_create_relationship(
                conn, domain_key=args.domain, kind="defines",
                from_key=p["concept"], to_key=p["document"],
                body=f"{p['concept']} defines {p['document']}",
                operator="ground-gov-concepts",
                attrs={"via": "extraction-evidence", "chunk_id": p["chunk_id"],
                       "quote": p["quote"]},
            )
            created += 1
        print(f"写入 defines：{created}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
