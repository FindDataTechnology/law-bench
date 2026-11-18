"""给政务线建一把「公文质量」尺子（幂等）。

    python3 scripts/seed_gov_rubric.py --dry-run
    python3 scripts/seed_gov_rubric.py

为什么是这些条目：政务公开的产物是**公文**，它的质量为题不在文采，而在
「这份公文是否可被检索、可被引用、可被追责」。所以八条判据全部是**可机器核对**的
事实，不是让模型打印象分：

1. 文号规范      有文号且形如「机关代字〔年份〕序号」
2. 发文机关明确   元数据里有机关名，且不是「其他/未知」这类占位
3. 成文日期在册   有日期，且不晚于抓取日
4. 标题与首段一致 标题在正文开头逐字出现（防抓串页）
5. 正文有实质内容 去掉标题/目录后仍长于阈值（防只有目录的空壳）
6. 无重复正文      同一正文哈希只应出现一次（防重复抓取）
7. 引用可解析      引用其他文件时带《书名》与文号（可据此建引用关系）
8. 附件与正文对应   声明了附件时，正文里能定位到附件标题

这些条目直接支撑本平台的三个下游用途：检索（5/6）、引用（1/7）、追责（2/3/4）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RUBRIC_NAME = "gov-document-quality"

#: (名称, 说明, 判定指引)。指引写给复核的人，也写给将来接机器判定的岗位。
CRITERIA: list[tuple[str, str, str]] = [
    ("文号规范", "公文应带规范文号",
     "形如「财办会〔2026〕31号」：机关代字 + 〔四位年份〕 + 序号。缺文号或格式不合法即不通过。"),
    ("发文机关明确", "应能指认发文机关",
     "取元数据 issuer；为空、或为「其他/未知/-」等占位即不通过——机关不明确无法追责。"),
    ("成文日期在册", "应有成文日期且不晚于抓取日",
     "日期缺失不通过；晚于抓取日说明抓到了草稿或预期发布日期，记录并复核。"),
    ("标题与首段一致", "标题应在正文开头逐字出现",
     "正文首段包含完整标题即通过；否则可能抓串页（拿到了别的文件正文）。"),
    ("正文有实质内容", "不能只有标题与目录",
     "去掉标题、目录、发文机关与日期行后，剩余正文长度需超过阈值（按文种设：公告可短，"
     "办法应长）；不达阈值即不通过。"),
    ("无重复正文", "同一正文只应出现一次",
     "按正文哈希去重；出现第二个相同哈希即不通过（说明同一份公文被抓了多次），"
     "应保留最新并标注。"),
    ("引用可解析", "引用其他文件时应可定位",
     "引用带《文件名》或文号即通过；只写「有关规定」不可解析，不通过。"),
    ("附件与正文对应", "声明附件时应能定位",
     "正文写明「附件：X」时，X 的标题应能在正文或同批次文件中找到；找不到即不通过。"),
]


def seed(conn: Any, *, domain_key: str) -> dict:
    """写入（或更新）该域的公文质量尺；返回 {rubric_id, criteria, visible}。"""
    from src.bench import domain_rubrics, workspaces
    from src.eval.db import now_iso

    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"域 {domain_key!r} 不存在")
    existing = conn.execute(
        "SELECT id FROM rubrics WHERE domain_id = %s AND name = %s",
        (domain["id"], RUBRIC_NAME),
    ).fetchone()
    if existing:
        rubric_id = existing["id"]
        conn.execute("DELETE FROM criteria WHERE rubric_id = %s", (rubric_id,))
    else:
        rubric_id = conn.execute(
            "INSERT INTO rubrics (name, context, source, source_path, description, "
            "created_at, domain_id) VALUES (%s,'check','platform-seed',%s,%s,%s,%s) "
            "RETURNING id",
            (RUBRIC_NAME, "scripts/seed_gov_rubric.py",
             "政务公开公文质量：可检索、可引用、可追责", now_iso(), domain["id"]),
        ).fetchone()["id"]
    for ordinal, (name, desc, guide) in enumerate(CRITERIA):
        conn.execute(
            "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
            "VALUES (%s,%s,%s,%s,%s)",
            (rubric_id, name, desc, guide, ordinal),
        )
    conn.commit()
    visible = domain_rubrics.effective_rubrics(
        conn, domain_path=domain.get("path") or domain["key"])
    return {"rubric_id": rubric_id, "criteria": len(CRITERIA),
            "visible": [r["name"] for r in visible]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default="gov")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.bench import workspaces
    from src.eval.db import connect

    conn = connect()
    try:
        domain = workspaces.get_domain(conn, domain_key=args.domain)
        if domain is None:
            print(f"域 {args.domain!r} 不存在", file=sys.stderr)
            return 1
        print(f"域 {args.domain}（id={domain['id']}）")
        print(f"尺子 {RUBRIC_NAME}：{len(CRITERIA)} 条判据")
        for name, desc, _guide in CRITERIA:
            print(f"  - {name}：{desc}")
        if args.dry_run:
            print("[dry-run] nothing written")
            return 0

        out = seed(conn, domain_key=args.domain)
        print(f"写入 rubric id={out['rubric_id']}，{out['criteria']} 条判据")
        print("该域可见尺子:", out["visible"])
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
