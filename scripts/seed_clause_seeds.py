#!/usr/bin/env python3
"""把 ``data/clause_seeds/*.yaml`` 装进 ``clauses`` 表（生产语料装载入口）。

为什么需要这个脚本：仓里**既有**语料（41 类 / 186 条种子条款）也有 loader
（``src.clauses.seed_manifest.load_one/load_all``），但此前**没有任何生产调用点**
——只有 tests 在用。结果是 ``clauses`` 表长期 0 行，``clause_review`` 一律报
``clause not found``、组装式 ``contract_generate`` 正文为空。这不是"爬虫没跑"，
是**语料没装**（两者不是一回事：爬虫产出的是合同全文，这里装的是逐条条款）。

用法::

    python3 scripts/seed_clause_seeds.py --dry-run             # 只校验清单，不写库
    python3 scripts/seed_clause_seeds.py                       # 全部 41 类
    python3 scripts/seed_clause_seeds.py --only bailment       # 单类
    python3 scripts/seed_clause_seeds.py --seeds-dir /tmp/x    # 指定清单目录

幂等：``load_one`` 按 ``source_doc_title='seed:<type>'`` 先删后建，可反复跑，
id 会换号（实测 1→6）——所以**不要**在别处写死 clause id。

回滚（一条语句回到装前状态）::

    DELETE FROM clauses WHERE source_doc_title LIKE 'seed:%';

装完所有条款都是 ``tag_review='pending'``：``is_assembly_ready`` 要求每个 tag 维
都是 ``approved``，所以组装式生成要**人工评审通过**后才收这些条款。本脚本不会
替人批准——那是评审决定，不是装载动作。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_SEEDS = REPO / "data" / "clause_seeds"


def _counts() -> tuple[int, int]:
    """(clauses 总数, seed 行数)；读不到库就返回 (-1, -1) 交给调用方判。"""
    import os

    import psycopg

    dsn = os.environ.get("database_url") or os.environ.get("DATABASE_URL")
    if not dsn:
        return -1, -1
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        total = conn.execute("SELECT count(*) FROM clauses").fetchone()[0]
        seeded = conn.execute(
            "SELECT count(*) FROM clauses WHERE source_doc_title LIKE 'seed:%'"
        ).fetchone()[0]
    return total, seeded


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default=None, help="只装一个 contract_type")
    ap.add_argument("--seeds-dir", default=str(DEFAULT_SEEDS), help="清单目录")
    ap.add_argument("--dry-run", action="store_true", help="只校验清单，不写库")
    args = ap.parse_args(argv)

    seeds = Path(args.seeds_dir)
    if not seeds.is_dir():
        print(f"清单目录不存在：{seeds}", file=sys.stderr)
        return 1

    from src.clauses.seed_manifest import load_all, load_one, load_manifest
    from src.clauses.tags import TAG_VOCAB, load_vocab_from_db

    # 必须先把 DB 里的 universal 维度并进 TAG_VOCAB 再校验清单：
    # 模块默认只有 source/stance，而 load_manifest 会校验 strength/risk/mandatory，
    # 不先并进来会把 `strength: standard` 判成非法值（首跑就栽在这里）。
    load_vocab_from_db()
    print(f"词汇表 universal 维度：{sorted(TAG_VOCAB.get(None, {}))}", flush=True)

    if args.dry_run:
        types = [args.only] if args.only else sorted(p.stem for p in seeds.glob("*.yaml"))
        total = 0
        for t in types:
            manifest = load_manifest(seeds / f"{t}.yaml")  # 校验失败即抛
            n = len(manifest.get("clauses") or [])
            total += n
            print(f"[ok] {t}: {n}")
        print(f"\ndry-run：{len(types)} 类 / {total} 条，未写库")
        return 0

    before = _counts()
    print(f"装前：clauses 总数={before[0]} seed 行={before[1]}", flush=True)

    if args.only:
        n = load_one(args.only, seeds_dir=seeds)
        print(f"[ok] {args.only}: {n} 条")
    else:
        result = load_all(seeds_dir=seeds)
        for k, v in sorted(result.items()):
            print(f"[ok] {k}: {v}")
        print(f"\n合计 {len(result)} 类 / {sum(result.values())} 条")

    after = _counts()
    print(f"装后：clauses 总数={after[0]} seed 行={after[1]}")
    print("提醒：条款均为 pending，组装生成需人工评审通过（tag_review approved）")
    print("回滚：DELETE FROM clauses WHERE source_doc_title LIKE 'seed:%';")
    return 0


if __name__ == "__main__":
    sys.exit(main())
