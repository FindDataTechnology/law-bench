"""分析 pipeline_runs 中的 clause/tag 迭代机会。

从 pipeline_runs 提取：
- 被频繁 exclude 的 custom clauses
- recommendations 中建议 reject 的 clauses
- eval score 与 clause 排除的相关性

输出：
1. 高频 exclude 清单（≥N 次）
2. 建议 reject 的汇总统计
3. 推荐操作列表（供人工 review）
"""
from __future__ import annotations

import json
from typing import Any

from src.eval.db import connect
from src.eval.pipeline_store import list_pipeline_runs, get_pipeline_run
from src.clauses.store import get_custom_clause


def analyze_exclude_patterns(limit: int = 50) -> dict[str, list[dict]]:
    """统计被 exclude 的 custom clauses."""
    exclude_counts: dict[int, list[int]] = {}  # clause_id -> [pipeline_ids]

    runs = list_pipeline_runs(limit=limit)
    for run in runs:
        pr = get_pipeline_run(run["id"])
        if not pr:
            continue

        actions = pr.get("actions_taken") or []
        for action in actions:
            excluded = action.get("excluded_ids", [])
            for cid in excluded:
                exclude_counts.setdefault(cid, []).append(run["id"])

    return {k: v for k, v in sorted(exclude_counts.items(), key=lambda x: -len(x[1]))}


def analyze_recommendations(limit: int = 50) -> list[dict]:
    """汇总 recommendations 中的 reject 建议."""
    recs: list[dict] = []

    runs = list_pipeline_runs(limit=limit)
    for run in runs:
        pr = get_pipeline_run(run["id"])
        if not pr:
            continue

        for rec in (pr.get("recommendations") or []):
            if isinstance(rec, dict) and rec.get("action") == "reject":
                recs.append({
                    "clause_id": rec.get("clause_id"),
                    "reason": rec.get("reason"),
                    "pipeline_id": run["id"],
                    "score": run.get("score"),
                    "all_pass": bool(run.get("all_pass")),
                })

    return recs


def correlate_score_with_exclusions(limit: int = 50) -> list[dict]:
    """分析 score 随 excluded 的变化趋势."""
    results: list[dict] = []

    runs = list_pipeline_runs(limit=limit)
    for run in runs:
        pr = get_pipeline_run(run["id"])
        if not pr:
            continue

        exclusion_count = sum(len(a.get("excluded_ids", [])) for a in (pr.get("actions_taken") or []))
        results.append({
            "pipeline_id": run["id"],
            "score": run.get("score"),
            "max_score": run.get("max_score"),
            "iteration": run.get("iteration"),
            "n_excluded": exclusion_count,
            "all_pass": bool(run.get("all_pass")),
        })

    return results


def generate_recommendations(
    exclude_counts: dict[str, list[dict]],
    recs: list[dict],
    threshold_exclude: int = 3,
    threshold_reject: int = 2,
) -> list[dict]:
    """生成推荐操作列表."""
    rec_list = []

    # 高频 exclude 推荐 reject
    for cid, pids in exclude_counts.items():
        if len(pids) >= threshold_exclude:
            clause = get_custom_clause(cid)
            rec_list.append({
                "type": "reject_clauses",
                "clause_id": cid,
                "section": clause.get("section") if clause else None,
                "body_preview": (clause.get("body") or "")[:100] + "..." if clause else None,
                "exclude_count": len(pids),
                "involved_pipelines": pids[:5],  # top 5
                "reason": f"在 {len(pids)} 次 pipeline 中被排除",
                "confidence": "high" if len(pids) >= 5 else "medium",
            })

    # recommendations 汇总
    reject_counts: dict[int, dict] = {}
    for r in recs:
        cid = r["clause_id"]
        if cid not in reject_counts:
            reject_counts[cid] = {"count": 0, "reasons": set()}
        reject_counts[cid]["count"] += 1
        if r.get("reason"):
            reject_counts[cid]["reasons"].add(r["reason"][:100])

    for cid, data in reject_counts.items():
        if data["count"] >= threshold_reject:
            clause = get_custom_clause(cid)
            rec_list.append({
                "type": "reject_clauses",
                "clause_id": cid,
                "section": clause.get("section") if clause else None,
                "body_preview": (clause.get("body") or "")[:100] + "..." if clause else None,
                "reject_count": data["count"],
                "reasons": list(data["reasons"])[:3],
                "confidence": "high" if data["count"] >= 5 else "medium",
            })

    # 按 confidence 和 count 排序
    def sort_key(r):
        weight = {"high": 2, "medium": 1}.get(r["confidence"], 0)
        count = max(r.get("exclude_count", 0), r.get("reject_count", 0))
        return (weight, count)

    return sorted(rec_list, key=sort_key, reverse=True)


def main(limit: int = 50, threshold_exclude: int = 3, threshold_reject: int = 2, output: str = None, db: Any = None):
    print("=" * 60)
    print("Clause Iteration Analysis Report")
    print("=" * 60)

    exclude_counts = analyze_exclude_patterns(limit)
    print(f"\n[1] 被排除的 Custom Clauses (出现次数: {len(exclude_counts)})")
    print("-" * 60)
    for cid, pids in list(exclude_counts.items())[:10]:
        print(f"  id={cid}: 被排除 {len(pids)} 次 ({', '.join(map(str, pids[:3]))})")

    recs = analyze_recommendations(limit)
    print(f"\n[2] Recommendations 中的 Reject 建议 (共 {len(recs)} 条)")
    print("-" * 60)

    score_trends = correlate_score_with_exclusions(limit)
    print(f"\n[3] Score vs Exclusion Trend (样本数：{len(score_trends)})")
    print("-" * 60)
    avg_score = sum(s.get("score", 0) for s in score_trends) / max(len(score_trends), 1)
    all_pass_rate = sum(1 for s in score_trends if s["all_pass"]) / max(len(score_trends), 1)
    print(f"  平均分：{avg_score:.2f}")
    print(f"  All-pass 率：{all_pass_rate*100:.1f}%")

    recommendations = generate_recommendations(exclude_counts, recs, threshold_exclude, threshold_reject)
    print(f"\n[4] 推荐操作列表 (阈值：exclude≥{threshold_exclude}, reject≥{threshold_reject})")
    print("-" * 60)
    if not recommendations:
        print("  （暂无高置信度推荐）")
    else:
        for i, r in enumerate(recommendations, 1):
            print(f"\n  #{i} [confidence:{r['confidence']}] id={r['clause_id']} section={r.get('section')}")
            print(f"      preview: {r.get('body_preview')}")
            if r.get("exclude_count"):
                print(f"      exclude_count: {r['exclude_count']}, pipelines: {r['involved_pipelines']}")
            if r.get("reject_count"):
                print(f"      reject_count: {r['reject_count']}, reasons: {r['reasons']}")
            print(f"      action: recommend clause_review(id={r['clause_id']}, status='rejected')")

    print("\n" + "=" * 60)
    print("Report complete. Use clause_review() to apply changes.")
    print("=" * 60)

    # Output JSON if requested
    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(recommendations, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Recommendations saved to: {output}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze clause iteration opportunities")
    parser.add_argument("--limit", type=int, default=50, help="Number of pipeline runs to analyze")
    parser.add_argument("--threshold-exclude", type=int, default=3, help="Exclude count threshold")
    parser.add_argument("--threshold-reject", type=int, default=2, help="Reject count threshold")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    args = parser.parse_args()

    main(limit=args.limit, threshold_exclude=args.threshold_exclude, threshold_reject=args.threshold_reject, output=args.output)
