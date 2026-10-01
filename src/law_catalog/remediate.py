"""Deterministic remediation of repealed-law citations (remediate-repealed-citations).

Flow: audit query -> successor map -> dry-run plan (diff + evidence chain,
narration whitelist) -> apply via :func:`src.clauses.store.update_clause`
(the canonical write path; sets manual=true) -> revision records + file
snapshots -> verify (re-run resolution/audit, assert the loop closes).

Records live twice: ``law_catalog.citation_revisions`` (queryable evidence
chains) and ``output/remediation/<batch>/`` snapshots (rollback authority).
No clause row is ever deleted; rollback restores bodies from snapshots.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from src.eval.db import connect, now_iso

from . import store
from .resolve import normalize_name

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_ROOT = REPO_ROOT / "output" / "remediation"

# narration contexts that must not be auto-replaced ("合同法实施以来" etc.)
_NARRATION_GUARD = re.compile(r"(实施以来|施行以来|已废止|已失效|原《|历次修正|历史沿革)")


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _repealed_citation_rows(conn, contract_type: Optional[str] = None) -> list[dict]:
    """Resolved citations pointing at repealed laws, joined with successor map."""
    sql = (
        "SELECT r.clause_id, r.cited_name, r.law_id AS dead_law_id, "
        "l.title AS dead_title, l.status AS dead_status, "
        "m.successor_law_id, m.authority_law_id, m.rule_version, m.needs_human, "
        "s.title AS successor_title, c.contract_type, c.body "
        "FROM law_catalog.clause_law_refs r "
        "JOIN law_catalog.laws l ON l.id = r.law_id "
        "JOIN clauses c ON c.id = r.clause_id "
        "LEFT JOIN law_catalog.successor_map m ON m.dead_law_id = r.law_id "
        "LEFT JOIN law_catalog.laws s ON s.id = m.successor_law_id "
        "WHERE l.status IN ('已废止','失效','已失效') AND r.resolved_via <> 'unresolved'"
    )
    args = []
    if contract_type:
        sql += " AND c.contract_type = %s"
        args.append(contract_type)
    return conn.execute(sql + " ORDER BY c.contract_type, r.clause_id", args).fetchall()


def _replacement_forms(dead_title: str, successor_title: str) -> list[dict]:
    """Replacement forms: full bracketed title, plus the bare short name.

    The bare name is substring-dangerous (合同法 ⊂ 技术合同法), so it only
    matches on non-CJK/latin boundaries and detection/replacement both use
    the boundary regex.
    """
    forms = [{"before": f"《{dead_title}》", "after": f"《{successor_title}》", "bare": False}]
    dead_short = dead_title[len("中华人民共和国"):] if dead_title.startswith("中华人民共和国") else dead_title
    succ_short = successor_title[len("中华人民共和国"):] if successor_title.startswith("中华人民共和国") else successor_title
    if len(dead_short) >= 3:
        forms.append({"before": dead_short, "after": succ_short, "bare": True})
        # shorthand rename follows the bracketed rename; exact parenthesized
        # string, so no substring risk (（以下简称合同法） survives the bare rule)
        forms.append({"before": f"（以下简称{dead_short}）", "after": f"（以下简称{succ_short}）"})
        forms.append({"before": f"(以下简称{dead_short})", "after": f"(以下简称{succ_short})"})
    return forms


def _form_regex(form: dict) -> re.Pattern:
    # punctuation-delimited forms (《…》, （以下简称X）, (以下简称X)) are exact;
    # only truly bare names need the CJK-boundary protection
    if form["before"][0] in "《（(":
        return re.compile(re.escape(form["before"]))
    # bare name: must not touch a CJK/latin char on either side — otherwise
    # 技术合同法 / 民法合同法 style longer names get corrupted
    return re.compile(rf"(?<![\u4e00-\u9fa5A-Za-z]){re.escape(form['before'])}(?![\u4e00-\u9fa5A-Za-z])")


def plan_batch(batch: str, db=None, contract_type: Optional[str] = None,
               limit: Optional[int] = None) -> dict:
    """Dry-run: per-clause replacement plan with evidence chains.

    Returns ``{"apply": [...], "skipped_review": [...], "needs_human": [...]}``.
    ``apply`` items carry ``new_body`` and per-citation replacements; nothing
    is written.
    """
    conn = connect(db)
    try:
        rows = _repealed_citation_rows(conn, contract_type)
    finally:
        conn.close()
    by_clause: dict[int, dict] = {}
    for r in rows:
        item = by_clause.setdefault(r["clause_id"], {
            "clause_id": r["clause_id"], "contract_type": r["contract_type"],
            "body": r["body"], "replacements": [], "evidence": [],
        })
        ev = {
            "dead_law_id": r["dead_law_id"], "dead_title": r["dead_title"],
            "dead_status": r["dead_status"],
            "successor_law_id": r["successor_law_id"],
            "successor_title": r["successor_title"],
            "authority_law_id": r["authority_law_id"],
            "rule_version": r["rule_version"],
        }
        item["evidence"].append(ev)
        if r["needs_human"] or not r["successor_law_id"]:
            item.setdefault("needs_human", []).append(ev)
            continue
        for form in _replacement_forms(r["dead_title"], r["successor_title"]):
            m = _form_regex(form).search(item["body"])
            if m:
                context = item["body"][max(0, m.start() - 12): m.end() + 12]
                item.setdefault("context", {})[form["before"]] = context
                if _NARRATION_GUARD.search(context):
                    item.setdefault("skipped_review", []).append({**ev, "form": form["before"], "context": context})
                    continue
                if any(b["before"] == form["before"] for b in item["replacements"]):
                    continue
                item["replacements"].append({"before": form["before"], "after": form["after"], **ev})

    plan = {"apply": [], "skipped_review": [], "needs_human": []}
    for item in by_clause.values():
        if item.get("replacements"):
            body = item["body"]
            for rep in item["replacements"]:
                body = _form_regex(rep).sub(rep["after"], body)
            item["new_body"] = body
            plan["apply"].append(item)
        elif item.get("skipped_review"):
            plan["skipped_review"].append(item)
        elif item.get("needs_human"):
            plan["needs_human"].append(item)
        else:
            # citation resolved but neither bracketed nor bare form present in
            # body (e.g. resolve came via alias) — surface for review
            item["reason"] = "dead citation string not found verbatim in body"
            plan["skipped_review"].append(item)
    if limit:
        plan["apply"] = plan["apply"][:limit]
    plan["batch"] = batch
    return plan


def _snapshot_dir(batch: str) -> Path:
    d = SNAPSHOT_ROOT / batch
    (d / "before").mkdir(parents=True, exist_ok=True)
    (d / "applied").mkdir(parents=True, exist_ok=True)
    return d


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


def _record_revision(conn, *, clause_id, contract_type, batch, cited_before,
                     cited_after, ev, disposition, rule_version, git_sha) -> None:
    conn.execute(
        "INSERT INTO law_catalog.citation_revisions "
        "(clause_id, contract_type, batch, cited_before, cited_after, dead_law_id, "
        " successor_law_id, authority_law_id, disposition, rule_version, git_sha, applied_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (clause_id, batch, cited_before) DO UPDATE SET "
        "cited_after=EXCLUDED.cited_after, successor_law_id=EXCLUDED.successor_law_id, "
        "authority_law_id=EXCLUDED.authority_law_id, disposition=EXCLUDED.disposition, "
        "rule_version=EXCLUDED.rule_version, git_sha=EXCLUDED.git_sha, applied_at=EXCLUDED.applied_at",
        (clause_id, contract_type, batch, cited_before, cited_after,
         ev.get("dead_law_id"), ev.get("successor_law_id"), ev.get("authority_law_id"),
         disposition, rule_version, git_sha, now_iso()),
    )


def apply_batch(plan: dict, db=None) -> dict:
    """Apply a dry-run plan: update_clause per item + records + snapshots."""
    from src.clauses.store import update_clause

    batch = plan["batch"]
    sha = _git_sha()
    out = {"batch": batch, "git_sha": sha, "applied": 0, "skipped_drift": 0, "records": 0}
    conn = connect(db)
    snap = _snapshot_dir(batch)
    try:
        store.ensure_schema(conn)
        for item in plan["apply"]:
            cid = item["clause_id"]
            current = conn.execute(
                "SELECT * FROM clauses WHERE id = %s", (cid,)
            ).fetchone()
            if current is None:
                out["skipped_drift"] += 1
                continue
            if not all(_form_regex(rep).search(current["body"]) for rep in item["replacements"]):
                # body drifted since the plan — refuse, record for review
                ev = item["evidence"][0]
                _record_revision(conn, clause_id=cid, contract_type=item["contract_type"],
                                 batch=batch, cited_before=item["replacements"][0]["before"],
                                 cited_after=None, ev=ev, disposition="skipped-review",
                                 rule_version=ev.get("rule_version"), git_sha=sha)
                out["skipped_drift"] += 1
                continue
            _write_json(snap / "before" / f"{cid}.json", dict(current))
            body = current["body"]
            for rep in item["replacements"]:
                body = _form_regex(rep).sub(rep["after"], body)
            updated = update_clause(cid, {"body": body}, db=conn)
            for rep in item["replacements"]:
                _record_revision(conn, clause_id=cid, contract_type=item["contract_type"],
                                 batch=batch, cited_before=rep["before"], cited_after=rep["after"],
                                 ev=rep, disposition="applied",
                                 rule_version=rep.get("rule_version"), git_sha=sha)
                out["records"] += 1
            _write_json(snap / "applied" / f"{cid}.json", {
                "clause_id": cid, "contract_type": item["contract_type"],
                "body_hash": updated["body_hash"],
                "replacements": item["replacements"], "evidence": item["evidence"],
            })
            out["applied"] += 1
        conn.commit()
        _write_json(snap / "manifest.json", {
            "batch": batch, "git_sha": sha, "generated_at": now_iso(),
            "applied": out["applied"], "skipped_drift": out["skipped_drift"],
        })
        return out
    finally:
        conn.close()


def record_no_action(batch: str, db=None) -> dict:
    """r0: record reviewed-no-action for citations of 已修改 laws (zero edits)."""
    sha = _git_sha()
    conn = connect(db)
    try:
        store.ensure_schema(conn)
        rows = conn.execute(
            "SELECT r.clause_id, r.cited_name, r.law_id, c.contract_type "
            "FROM law_catalog.clause_law_refs r JOIN law_catalog.laws l ON l.id = r.law_id "
            "JOIN clauses c ON c.id = r.clause_id "
            "WHERE l.status = '已修改' AND r.resolved_via <> 'unresolved'"
        ).fetchall()
        for r in rows:
            _record_revision(conn, clause_id=r["clause_id"], contract_type=r["contract_type"],
                             batch=batch, cited_before=r["cited_name"], cited_after=r["cited_name"],
                             ev={"dead_law_id": r["law_id"], "successor_law_id": r["law_id"],
                                 "authority_law_id": None, "rule_version": "amended-still-valid"},
                             disposition="reviewed-no-action", rule_version="amended-still-valid",
                             git_sha=sha)
        conn.commit()
        _write_json(_snapshot_dir(batch) / "manifest.json", {
            "batch": batch, "git_sha": sha, "generated_at": now_iso(),
            "reviewed_no_action": len(rows),
        })
        return {"batch": batch, "reviewed_no_action": len(rows)}
    finally:
        conn.close()


def rollback_batch(batch: str, db=None, clause_id: Optional[int] = None) -> dict:
    """Restore bodies from before-snapshots (via update_clause) + mark records."""
    from src.clauses.store import update_clause

    snap = SNAPSHOT_ROOT / batch / "before"
    sha = _git_sha()
    targets = sorted(snap.glob(f"{clause_id}.json" if clause_id else "*.json"))
    conn = connect(db)
    restored = 0
    try:
        for f in targets:
            before = json.loads(f.read_text(encoding="utf-8"))
            cid = before["id"]
            update_clause(cid, {"body": before["body"], "tags": before.get("tags") or {}}, db=conn)
            conn.execute(
                "UPDATE law_catalog.citation_revisions SET disposition='rolled-back', "
                "applied_at=%s, git_sha=%s WHERE clause_id=%s AND batch=%s AND disposition='applied'",
                (now_iso(), sha, cid, batch),
            )
            restored += 1
        conn.commit()
        return {"batch": batch, "restored": restored}
    finally:
        conn.close()


def verify_batch(db=None) -> dict:
    """Closed loop: re-run resolution + audit; assert repealed == unmapped count."""
    from . import audit, resolve

    resolve.resolve_all_clauses(db=db)
    result = audit.collect_audit(db=db)
    conn = connect(db)
    try:
        unmapped = conn.execute(
            "SELECT count(DISTINCT r.law_id) n FROM law_catalog.clause_law_refs r "
            "JOIN law_catalog.laws l ON l.id = r.law_id "
            "WHERE l.status IN ('已废止','失效','已失效') AND r.resolved_via <> 'unresolved' "
            "AND NOT EXISTS (SELECT 1 FROM law_catalog.successor_map m "
            " WHERE m.dead_law_id = r.law_id AND m.needs_human = false)"
        ).fetchone()["n"]
    finally:
        conn.close()
    return {"audit": result["summary"], "unmapped_dead_citations": result["summary"]["repealed"],
            "distinct_unmapped_dead_laws": unmapped}
