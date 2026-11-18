"""对已取入的政务公文跑一次真实评测，落 eval_runs + eval_criteria_results。

    python3 scripts/eval_gov_documents.py --dry-run
    python3 scripts/eval_gov_documents.py --limit 14

为什么要有这一步：`scripts/seed_gov_rubric.py` 只是**登记了尺子**，`last_run` 仍是
None。缺口消失不该由一次 seed 造成——只有真的量过一遍，这把尺子才从声明变成测量。

判据本身在 `packs/gov/doc_checks.py`（确定性、无模型）；本脚本只负责取文档、
跑判据、写结果，并把 run 归属到该域的 rubric 上（`rubric_domain_id`）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import packs.gov  # noqa: E402,F401
from packs.gov.doc_checks import CHECKS  # noqa: E402

RUBRIC_NAME = "gov-document-quality"


def _load_documents(conn, *, library_key: str, source_key: str, limit: int) -> list[dict]:
    """取已取入本体的公文正文 + 元数据（只读语料表，不碰本体）。"""
    import psycopg
    from psycopg.rows import dict_row

    from src.bench import corpus_catalog, libraries

    lib = libraries.get_library(conn, library_key=library_key)
    loc = libraries.resolve_location(lib)
    src = next(s for s in libraries.list_sources(conn, library_id=lib["id"])
               if s["source_key"] == source_key)
    mapping = corpus_catalog.document_mapping(src)
    table = mapping.get("table") or src["uri"]

    # 只评「已经取入本体」的文档：没进本体的东西评了也没有意义。
    keys = {
        r["external_key"]
        for r in conn.execute(
            "SELECT external_key FROM knowledge_units WHERE namespace = 'gov' "
            "AND kind = 'document' AND (tags->>'deleted') IS NULL",
        ).fetchall()
    }
    out: list[dict] = []
    hashes: dict[str, int] = {}
    with psycopg.connect(loc["dsn_env"], connect_timeout=10, row_factory=dict_row) as ext:
        # 不要按 id 倒序先截断：已取入本体的文档可能不在最新 N 条里（实测最新的
        # 56 条里一条都对不上，真正的 13 份在中间）。先取全量再按本体键筛，最后截断。
        rows = ext.execute(
            f"SELECT {mapping['id']} AS id, {mapping['title']} AS title, "
            f"{mapping['text']} AS text, metadata, content_hash FROM {table} "
            f"WHERE metadata->>'issuer' IS NOT NULL ORDER BY {mapping['id']} DESC LIMIT 2000",
        ).fetchall()
    for row in rows:
        meta = row.get("metadata") or {}
        if isinstance(meta, str):
            meta = json.loads(meta or "{}")
        title = (row.get("title") or "").strip()
        if not title:
            continue
        # 与本体里的文档单位对齐（键是按归名规则折出来的）
        from src.bench import keys as k

        canon = k.fold(title, k.rules_for("gov"))[0]
        if canon not in keys:
            continue
        h = row.get("content_hash") or ""
        hashes[h] = hashes.get(h, 0) + 1
        out.append({
            "id": str(row["id"]),
            "title": title,
            "text": row.get("text") or "",
            "issuer": (meta.get("issuer") or "").strip(),
            "date": (meta.get("doc_date") or "").strip(),
            "content_hash": h,
        })
        if len(out) >= limit:
            break
    for doc in out:
        doc["seen_hashes"] = hashes
    return out


def run(conn, *, domain_key: str = "gov", limit: int = 14, dry_run: bool = True) -> dict:
    from src.bench import domain_rubrics, workspaces
    from src.eval.db import now_iso

    rubric = conn.execute(
        "SELECT r.id, c.name, c.id AS criterion_row FROM rubrics r "
        "LEFT JOIN criteria c ON c.rubric_id = r.id WHERE r.name = %s "
        "ORDER BY c.ordinal", (RUBRIC_NAME,),
    ).fetchall()
    if not rubric:
        raise ValueError(f"rubric {RUBRIC_NAME!r} 尚未登记，先跑 scripts/seed_gov_rubric.py")
    rubric_id = rubric[0]["id"]

    docs = _load_documents(conn, library_key="text-library", source_key="gov", limit=limit)
    results = []
    for doc in docs:
        for name, check in CHECKS:
            passed, note = check(doc)
            results.append({"doc": doc["id"], "title": doc["title"], "criterion": name,
                            "passed": passed, "note": note})
    per_criterion = {
        name: sum(1 for r in results if r["criterion"] == name and r["passed"])
        for name, _ in CHECKS
    }
    n_passed = sum(1 for r in results if r["passed"])
    total = len(results)
    summary = {"documents": len(docs), "checks": total, "passed": n_passed,
               "per_criterion": per_criterion,
               "failed_examples": [r for r in results if not r["passed"]][:5]}
    if dry_run:
        return {**summary, "dry_run": True, "run_id": None}

    score = round(n_passed / total, 4) if total else 0.0
    run_id = conn.execute(
        "INSERT INTO eval_runs (rubric_name, contract_path, task_desc, score, max_score, "
        "all_pass, n_criteria, n_passed, summary, judge_model, scored_at, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (RUBRIC_NAME, None, f"政务公文质量（{len(docs)} 份）", score, 1.0,
         1 if n_passed == total else 0, total, n_passed,
         json.dumps(per_criterion, ensure_ascii=False), "deterministic-checks",
         now_iso(), now_iso()),
    ).fetchone()["id"]
    ordinal = 0
    for r in results:
        conn.execute(
            "INSERT INTO eval_criteria_results (run_id, criterion_id, title, verdict, "
            "reasoning, ordinal) VALUES (%s,%s,%s,%s,%s,%s)",
            (run_id, f"{r['criterion']}#{r['doc']}", r["criterion"],
             "pass" if r["passed"] else "fail", r["note"], ordinal),
        )
        ordinal += 1
    conn.commit()
    domain_rubrics.attribute_run(conn, run_id=run_id, rubric_id=rubric_id)
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    return {**summary, "dry_run": False, "run_id": run_id, "score": score,
            "domain": domain["key"] if domain else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default="gov")
    ap.add_argument("--limit", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.eval.db import connect

    conn = connect()
    try:
        out = run(conn, domain_key=args.domain, limit=args.limit, dry_run=args.dry_run)
        print(f"评测文档：{out['documents']}，检查项：{out['checks']}，通过：{out['passed']}")
        for name, n in out["per_criterion"].items():
            print(f"  {name:<12} {n}/{out['documents']}")
        if out["failed_examples"]:
            print("未通过示例：")
            for r in out["failed_examples"]:
                print(f"  - [{r['criterion']}] {r['title'][:26]}：{r['note']}")
        print(("[dry-run] nothing written" if out["dry_run"]
               else f"写入 eval_runs id={out['run_id']}，score={out['score']}"))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
