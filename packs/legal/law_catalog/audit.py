"""Citation audit: classify every clause law citation by the cited law's status.

Classification uses ONLY the catalog ``status`` column - never ``expiry``
(its real-world semantics is 施行日期, effective date):

  repealed  - status IN ('已废止', '失效')   → 引用已废法律
  amended   - status = '已修改'              → 已修改（多数仍有效，仅被修正）
  fallback  - unresolved citation, replica miss, or NULL/dirty status
  ok        - 有效 / 尚未生效 / other non-problem statuses

Pure collection + deterministic markdown rendering; nothing here writes to
clauses.
"""

from __future__ import annotations

from datetime import datetime, timezone

REPEALED_STATUSES = {"已废止", "失效", "已失效"}
AMENDED_STATUS = "已修改"
# "未知" is the catalog's normalized no-source-value status (2026-09-26 export
# vocabulary: 有效/已修改/已废止/未知/尚未生效/失效/已失效) — it falls to the
# fallback category by design, never guessed.
OK_STATUSES = {"有效", "尚未生效"}

CATEGORY_ORDER = ("repealed", "amended", "fallback", "ok")
CATEGORY_ZH = {
    "repealed": "引用已废法律",
    "amended": "已修改（多数仍有效，仅被修正）",
    "fallback": "兜底清单（未解析或状态缺失/脏值）",
    "ok": "正常",
}


def classify(law_status, resolved_via: str) -> str:
    """Map one citation to its audit category."""
    if resolved_via == "unresolved" or not law_status:
        return "fallback"
    s = str(law_status).strip()
    if s in REPEALED_STATUSES:
        return "repealed"
    if s == AMENDED_STATUS:
        return "amended"
    if s in OK_STATUSES:
        return "ok"
    return "fallback"  # dirty values (e.g. "sxx:3") - never guessed


def collect_audit(db=None) -> dict:
    """Group all resolution results by audit category.

    Returns ``{"summary": {cat: n}, "findings": {cat: [row,...]}, "snapshot": {...}}``
    with rows ordered by (contract_type, clause_id, cited_name) - deterministic
    for a fixed corpus + catalog snapshot.
    """
    from . import store

    rows = store.list_resolutions(db=db)
    findings: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_ORDER}
    summary: dict[str, int] = {cat: 0 for cat in CATEGORY_ORDER}
    for r in rows:
        cat = classify(r["law_status"], r["resolved_via"])
        row = dict(r)
        row["category"] = cat
        findings[cat].append(row)
        summary[cat] += 1
    return {
        "summary": summary,
        "findings": findings,
        "total": len(rows),
        "snapshot": store.catalog_snapshot(db=db),
    }


def render_report(audit: dict) -> str:
    """Deterministic markdown report for the audit result."""
    s = audit["summary"]
    snap = audit["snapshot"]
    lines: list[str] = [
        "# 条款引法审计报告",
        "",
        f"目录快照：{snap['rows']} 部法规，max_id={snap['max_id']}，"
        f"导入时间 {snap['imported_at'] or '—'}",
        f"审计范围：{audit['total']} 条引用",
        "",
        "| 分类 | 数量 |",
        "| --- | ---: |",
    ]
    for cat in CATEGORY_ORDER:
        lines.append(f"| {CATEGORY_ZH[cat]} | {s[cat]} |")
    lines.append("")

    detail_order = ("repealed", "amended", "fallback")
    for cat in detail_order:
        lines.append(f"## {CATEGORY_ZH[cat]}（{s[cat]}）")
        lines.append("")
        if not audit["findings"][cat]:
            lines.append("（无）")
            lines.append("")
            continue
        lines.append(
            "| 合同类型 | 条款 | 引用名 | 目录法规 | 状态 | 解析方式 |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for it in audit["findings"][cat]:
            lines.append(
                "| {ct} | #{cid} {sec} | 《{name}》 | {title} | {st} | {via} |".format(
                    ct=it.get("contract_type") or "—",
                    cid=it["clause_id"],
                    sec=it.get("section") or "—",
                    name=it["cited_name"],
                    title=it.get("title") or "—",
                    st=it.get("law_status") or "—",
                    via=it["resolved_via"],
                )
            )
        lines.append("")
    return "\n".join(lines)


def write_report(audit: dict, path: str) -> str:
    """Render + write the report file; returns the markdown."""
    md = render_report(audit)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(md + "\n")
    return md


def generated_at() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
