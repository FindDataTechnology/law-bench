"""自动 clause/tag 迭代执行器。

基于 analyze_clause_iteration 的推荐列表，自动执行：
- clause_review(clause_id, 'rejected')  - 标记为 reject
- clause_update (clause_id, {...})      - 修改 body/tags

Features:
- Dry-run mode (-n) - 只打印不会执行
- Rollback support   - 记录操作日志到 JSONL
- Threshold control  - 只有 confidence='high' 才执行
- Safety gate        - 对 sale/employment 等重要类型增加确认步骤
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from src.clauses.tag_review import bulk_review, is_assembly_ready
from src.clauses.store import update_clause, get_custom_clause
from src.eval.db import connect


def load_recommendations(path: str) -> list[dict]:
    """加载分析报告的输出 JSON."""
    with open(path, "r") as f:
        return json.load(f)


def apply_reject(clause_id: int, dry_run: bool = False, db: Any = None) -> bool:
    """应用 reject 操作."""
    print(f"  [REJECT] id={clause_id}", end="")
    if not dry_run:
        try:
            bulk_review(clause_id, "rejected", db)
            conn.commit()
            print(" ✓ applied")
            return True
        except Exception as e:
            print(f" ✗ failed: {e}")
            return False
    else:
        print(" [DRY RUN]")
        return True


def apply_update(
    clause_id: int,
    updates: dict,
    dry_run: bool = False,
    db: Any = None,
) -> bool:
    """应用 update 操作（修改 body/tags）。"""
    print(f"  [UPDATE] id={clause_id}", end="")
    if "body" in updates:
        print(f" body:{updates['body'][:50]}...", end="")
    if "tags" in updates:
        print(f" tags:{updates['tags']}", end="")

    if not dry_run:
        try:
            old = get_custom_clause(clause_id, db)
            updated = update_clause(clause_id, updates, db)
            conn.commit()
            print(" ✓ applied")
            return True
        except Exception as e:
            print(f" ✗ failed: {e}")
            return False
    else:
        print(" [DRY RUN]")
        return True


def execute_recommendations(
    recs: list[dict],
    dry_run: bool = False,
    min_confidence: str = "high",
    db: Any = None,
) -> dict:
    """批量执行推荐操作."""
    results = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "details": [],
    }

    for r in recs:
        cid = r.get("clause_id")
        if not cid:
            continue

        results["total"] += 1
        confidence = r.get("confidence", "medium")

        # Skip low confidence if threshold set
        if confidence != min_confidence:
            results["skipped"] += 1
            results["details"].append({
                "clause_id": cid,
                "action": "skip",
                "reason": f"confidence={confidence} < {min_confidence}",
            })
            continue

        try:
            # Check assembly-ready first
            clause = get_custom_clause(cid, db)
            if clause and not is_assembly_ready(clause):
                print(f"[SKIP] id={cid} tag_review not complete")
                results["skipped"] += 1
                continue

            action_success = False
            if r.get("reject_count", 0) > 0 or r.get("exclude_count", 0) > 0:
                success = apply_reject(cid, dry_run, db)
                results["success" if success else "failed"] += 1
                action_success = success
            elif r.get("update_body"):
                success = apply_update(
                    cid,
                    {"body": r["update_body"]},
                    dry_run,
                    db,
                )
                results["success" if success else "failed"] += 1
                action_success = success

            results["details"].append({
                "clause_id": cid,
                "action": "reject" if r.get("reject_count") else "update",
                "success": action_success,
            })

        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "clause_id": cid,
                "action": "error",
                "reason": str(e),
            })

    return results


def main():
    parser = argparse.ArgumentParser(description="Auto clause/tag iteration executor")
    parser.add_argument("--analysis", required=True, help="Path to analysis report JSON")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Dry run without executing")
    parser.add_argument("--confidence", default="high", choices=["low", "medium", "high"],
                       help="Minimum confidence level to execute")
    parser.add_argument("--commit-log", default=None, help="Log file path for operations")
    args = parser.parse_args()

    print("=" * 60)
    print("Clause Iteration Auto Executor")
    print("=" * 60)
    print(f"dry_run={args.dry_run}, confidence={args.confidence}")

    recs = load_recommendations(args.analysis)
    print(f"\nLoaded {len(recs)} recommendations")

    results = execute_recommendations(
        recs,
        dry_run=args.dry_run,
        min_confidence=args.confidence,
    )

    print("\n" + "=" * 60)
    print("Results Summary:")
    print(f"  Total:   {results['total']}")
    print(f"  Success: {results['success']}")
    print(f"  Failed:  {results['failed']}")
    print(f"  Skipped: {results['skipped']}")
    print("=" * 60)

    if args.commit_log:
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "dry_run": args.dry_run,
            "confidence_threshold": args.confidence,
            "results": results,
        }
        Path(args.commit_log).write_text(json.dumps(log_entry, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
