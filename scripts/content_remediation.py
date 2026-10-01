#!/usr/bin/env python3
"""Production clause-library remediation driver (reversible, batch-scoped).

Implements the ``content-remediation`` change. Every batch:

1. selects its target ids from the LIVE database (never from a stale dump),
2. snapshots the full pre-mutation row to ``output/remediation/<batch>/before/``,
3. applies mutations through the shared write paths only
   (``update_clause`` for bodies; bulk_review / a narrow tag_review-only
   UPDATE for review states — ``update_clause`` cannot write tag_review),
4. records per-clause results to ``output/remediation/<batch>/applied/``.

``--rollback <batch>`` restores bodies + tag_review from the before
snapshots (idempotent: re-running a completed rollback changes nothing).
No DELETE is ever issued; duplicates are rejected via tag_review and can be
revived by re-approval or rollback.

Batches (see openspec/changes/content-remediation/design.md D4):
  b0-data   strip ``_``-prefixed metadata keys from tag_review
  b1        reject exact body_hash duplicates among tagged clauses (keep min id)
  b2        apply reviewed region-generalization drafts (--drafts file)
  b3        strip extraction artifacts deterministically (sign shells,
            underscore blanks, table fragments)
  b4        apply curated spot-fix drafts (--drafts file)

Examples::

    python scripts/content_remediation.py --list
    python scripts/content_remediation.py --batch b0-data --dry-run
    python scripts/content_remediation.py --batch b3 --limit 50
    python scripts/content_remediation.py --rollback b0-data

Database: reads ``database_url``/``DATABASE_URL`` (see src/eval/db.py);
``--database-url`` overrides (e.g. the kubectl port-forward DSN
``postgresql://app:...@localhost:15433/law_bench``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

# Do NOT override an explicitly exported DATABASE_URL with .env values.
load_dotenv(override=False)

from psycopg.types.json import Jsonb  # noqa: E402

from src.clauses.audit import region_lint  # noqa: E402
from src.clauses.content_checks import (  # noqa: E402
    HEADER_RE,
    TINY_BODY,
    UNDERSCORE_RE,
)
from src.clauses.store import _row_to_dict, update_clause  # noqa: E402
from src.clauses.tag_review import METADATA_PREFIX, bulk_review  # noqa: E402
from src.eval.db import connect  # noqa: E402

REMEDIATION_DIR = Path("output/remediation")

# Clauses whose region mentions are scenario-intrinsic (never rewritten).
B2_EXEMPT_IDS = {2370}

# scenario-bearing region-leak targets for b2 (2026-09-15 audit, minus exempt).
B2_IDS = [
    4507, 4709, 1326, 2242, 7956, 2755, 1784, 5379, 4662, 2060,
    2252, 2327, 3406, 2709, 2930, 3711, 3810,
]

# --------------------------------------------------------------------------- #
# db helpers
# --------------------------------------------------------------------------- #
def load_all_clauses() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM clauses").fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def get_clause_row(clause_id: int) -> dict | None:
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM clauses WHERE id = %s", (clause_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_dict(r) if r else None


def set_tag_review(clause_id: int, tag_review: dict) -> None:
    """Narrow review-state write (update_clause does not cover tag_review)."""
    conn = connect()
    try:
        conn.execute(
            "UPDATE clauses SET tag_review = %s WHERE id = %s",
            (Jsonb(tag_review), clause_id),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# snapshot / manifest
# --------------------------------------------------------------------------- #
def batch_dir(batch: str) -> Path:
    d = REMEDIATION_DIR / batch
    (d / "before").mkdir(parents=True, exist_ok=True)
    (d / "applied").mkdir(parents=True, exist_ok=True)
    return d


def snapshot_before(batch: str, clause: dict) -> Path:
    p = batch_dir(batch) / "before" / f"{clause['contract_type']}_{clause['id']}.json"
    p.write_text(json.dumps(clause, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def record_applied(batch: str, clause: dict, fields: dict, source: str) -> Path:
    p = batch_dir(batch) / "applied" / f"{clause['contract_type']}_{clause['id']}.json"
    p.write_text(json.dumps({
        "id": clause["id"],
        "contract_type": clause["contract_type"],
        "section": clause.get("section"),
        "fields_updated": sorted(fields),
        "new_values": fields,
        "source": source,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def write_manifest(batch: str, **kw) -> Path:
    p = batch_dir(batch) / "manifest.json"
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
    except Exception:
        sha = "unknown"
    kw.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    kw.setdefault("git_sha", sha)
    p.write_text(json.dumps({"batch": batch, **kw}, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    return p


def load_manifest(batch: str) -> dict:
    p = REMEDIATION_DIR / batch / "manifest.json"
    if not p.exists():
        raise SystemExit(f"no manifest for batch {batch!r} — nothing to roll back")
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# b3 artifact rules (design D5: deterministic + conservative)
# --------------------------------------------------------------------------- #
_SHELL_KEYWORD = (
    r"签字|签章|盖章|签订地点|签订日期|签署地点|签署日期|签订时间|签署时间"
    r"|身份证号|联系电话|电子邮箱|邮政编码|邮编|委托代理人|经办人|传真"
    r"|单位联系人|联系人|开户银行|帐号|账号"
)
# A shell FIELD line: keyword + colon + blank/placeholder value, no sentence
# punctuation anywhere in the line. Value tail tolerates only filler chars
# (underscores, slots, digits) and date nouns (年月日) — prose never matches.
_SHELL_LINE_RE = re.compile(
    r"^\s*[^，。；！？]{0,30}"           # short label part without prose punctuation
    r"(?:" + _SHELL_KEYWORD + r")"
    r"[^，。；！？]{0,30}"               # rest of the line, still punctuation-free
    r"[：:]\s*[_＿{}\s.a-zA-Z\du年月日号码份]{0,44}\s*$"
)
_NOPROSE_RE = re.compile(r"（以下无正文[^）]*）")
_DATE_BLANK_RE = re.compile(r"[_＿]{2,}\s*年\s*[_＿]{1,}\s*月\s*[_＿]{1,}\s*日")
_COPIES_RE = re.compile(r"一式\s*[_＿]{2,}\s*份")
_HOLD_RE = re.compile(r"各执\s*[_＿]{2,}\s*份")


# Sections whose purpose IS the signature block: stripping there produces
# incoherent fragments — leave whole-block clauses alone (template-shell
# question, handled outside this batch).
SIGN_SECTION_WHITELIST = {"签署信息", "签署", "签字盖章", "签署页", "签章"}


def _is_shell_line(line: str) -> bool:
    """Shell FIELD line, whitespace-insensitive (matches 经 办 人, 签 约 时 间)."""
    norm = re.sub(r"[\s\u3000]+", "", line)
    return bool(_SHELL_LINE_RE.search(norm))


def _clean_body(body: str) -> tuple[str, list[str]]:
    """Apply b3 rules. Returns (new_body, list-of-rules-hit)."""
    rules: list[str] = []
    lines = body.split("\n")
    out: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        # table fragment block: 2+ consecutive pipe lines
        if line.lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            if j - i >= 2:
                rules.append("table_fragment")
                i = j
                continue
        out.append(line)
        i += 1

    result = []
    for line in out:
        if _is_shell_line(line):
            rules.append("shell_line")
            continue
        if _NOPROSE_RE.fullmatch(line.strip()):
            rules.append("shell_line")
            continue
        result.append(line)
    new = "\n".join(result)

    def _sub_copies(m: re.Match) -> str:
        rules.append("underscore_blanks")
        return "一式{{contract_copies}}份"

    new = _COPIES_RE.sub(_sub_copies, new)

    def _sub_hold(m: re.Match) -> str:
        rules.append("underscore_blanks")
        return "各执{{party_hold_count}}份"

    new = _HOLD_RE.sub(_sub_hold, new)

    def _sub_date(m: re.Match) -> str:
        rules.append("underscore_blanks")
        return "{{sign_date}}"

    new = _DATE_BLANK_RE.sub(_sub_date, new)

    new = re.sub(r"\n{3,}", "\n\n", new).strip()
    return new, rules


def strip_artifacts(clause: dict) -> tuple[str | None, list[str]]:
    """Return (new_body, rules) or (None, []) when nothing to strip."""
    body = clause.get("body") or ""
    new, rules = _clean_body(body)
    if not rules or new == body.strip():
        return None, []
    if len(new) < TINY_BODY:
        return None, []  # stripped body would be a useless remnant — keep original
    return new, rules


# --------------------------------------------------------------------------- #
# batches
# --------------------------------------------------------------------------- #
def select_b0() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id FROM clauses WHERE EXISTS ("
            "  SELECT 1 FROM jsonb_object_keys(tag_review) k"
            "  WHERE k LIKE %s ESCAPE '\\')",
            ("\\" + METADATA_PREFIX + "%",),
        ).fetchall()
    finally:
        conn.close()
    return [r["id"] for r in rows]


def run_b0(clauses_by_id: dict, dry_run: bool, limit: int) -> dict:
    ids = select_b0()
    if limit:
        ids = ids[:limit]
    stats = {"selected": len(ids), "applied": 0, "skipped": 0}
    for cid in ids:
        clause = clauses_by_id.get(cid) or get_clause_row(cid)
        review = clause.get("tag_review") or {}
        cleaned = {k: v for k, v in review.items()
                   if not k.startswith(METADATA_PREFIX)}
        if cleaned == review:
            stats["skipped"] += 1
            continue
        print(f"  b0 #{cid} [{clause['contract_type']}]: "
              f"drop {sorted(k for k in review if k not in cleaned)}")
        if not dry_run:
            snapshot_before("b0-data", clause)
            set_tag_review(cid, cleaned)
            record_applied("b0-data", clause, {"tag_review": cleaned},
                           "strip metadata keys")
        stats["applied"] += 1
    return stats


def select_b1() -> list[int]:
    """Victim ids: non-canonical members of body_hash dup groups (tagged,
    not already rejected in any dim)."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT body_hash, array_agg(id ORDER BY id) AS ids "
            "FROM clauses "
            "WHERE tags->>'source' = 'tagged' AND body_hash IS NOT NULL "
            "  AND NOT EXISTS ("
            "    SELECT 1 FROM jsonb_each_text(tag_review) WHERE value = 'rejected')"
            "GROUP BY body_hash HAVING count(*) > 1"
        ).fetchall()
    finally:
        conn.close()
    victims: list[int] = []
    for r in rows:
        victims.extend(r["ids"][1:])
    return victims


def run_b1(victims: list[int], clauses_by_id: dict, dry_run: bool, limit: int) -> dict:
    if limit:
        victims = victims[:limit]
    stats = {"selected": len(victims), "applied": 0, "skipped": 0}
    for cid in victims:
        clause = clauses_by_id.get(cid) or get_clause_row(cid)
        if clause is None:
            print(f"  b1 #{cid}: clause not found, skipping")
            stats["skipped"] += 1
            continue
        print(f"  b1 #{cid} [{clause['contract_type']}]: reject duplicate body")
        if not dry_run:
            snapshot_before("b1", clause)
            bulk_review(cid, "rejected")
            record_applied("b1", clause, {"tag_review": "bulk rejected"},
                           "dedupe (keep min id of body_hash group)")
        stats["applied"] += 1
    return stats


def run_b2(drafts: dict, clauses_by_id: dict, dry_run: bool, limit: int) -> dict:
    stats = {"selected": 0, "applied": 0, "skipped": 0, "rejected_drafts": 0}
    for cid in B2_IDS:
        if cid in B2_EXEMPT_IDS:
            continue
        new_body = (drafts.get(str(cid)) or drafts.get(cid))
        if not new_body:
            stats["skipped"] += 1
            continue
        stats["selected"] += 1
        if limit and stats["selected"] > limit:
            stats["selected"] -= 1
            break
        clause = clauses_by_id.get(cid) or get_clause_row(cid)
        if clause is None:
            print(f"  b2 #{cid}: clause not found, skipping")
            stats["skipped"] += 1
            continue
        old = (clause.get("body") or "").strip()
        new_body = new_body.strip()
        problems = []
        if new_body == old:
            problems.append("draft identical to current body")
        if region_lint(new_body):
            problems.append(f"region_lint hits: {region_lint(new_body)}")
        if new_body.startswith("##"):
            problems.append("draft starts with section heading")
        if problems:
            print(f"  b2 #{cid}: DRAFT REJECTED — {'; '.join(problems)}")
            stats["rejected_drafts"] += 1
            continue
        print(f"  b2 #{cid} [{clause['contract_type']}]: apply region rewrite")
        if not dry_run:
            snapshot_before("b2", clause)
            update_clause(cid, {"body": new_body})
            record_applied("b2", clause, {"body": new_body},
                           "region generalization (reviewed draft)")
        stats["applied"] += 1
    return stats


def run_b3(clauses: list[dict], dry_run: bool, limit: int) -> dict:
    stats = {"selected": 0, "applied": 0, "skipped": 0}
    for clause in clauses:
        body = clause.get("body") or ""
        if (clause.get("section") or "") in SIGN_SECTION_WHITELIST:
            stats["skipped"] += 1
            continue
        new, rules = strip_artifacts(clause)
        if new is None:
            stats["skipped"] += 1
            continue
        stats["selected"] += 1
        if limit and stats["selected"] > limit:
            stats["selected"] -= 1
            break
        print(f"  b3 #{clause['id']} [{clause['contract_type']}]: "
              f"strip {sorted(set(rules))}")
        if not dry_run:
            snapshot_before("b3", clause)
            update_clause(clause["id"], {"body": new})
            record_applied("b3", clause, {"body": new},
                           f"artifact strip: {sorted(set(rules))}")
        stats["applied"] += 1
    return stats


def run_b4(drafts: dict, clauses_by_id: dict, dry_run: bool) -> dict:
    stats = {"selected": 0, "applied": 0, "skipped": 0, "rejected_drafts": 0}
    for cid_str, new_body in drafts.items():
        cid = int(cid_str)
        entry = drafts[cid_str]
        if isinstance(entry, dict):
            action = entry.get("action", "rewrite")
            new_body = entry.get("body")
        else:
            action, new_body = "rewrite", new_body
        clause = clauses_by_id.get(cid) or get_clause_row(cid)
        if clause is None:
            print(f"  b4 #{cid}: clause not found, skipping")
            stats["skipped"] += 1
            continue
        if action == "keep":
            print(f"  b4 #{cid}: keep (triaged, no change)")
            stats["skipped"] += 1
            continue
        if action == "reject":
            print(f"  b4 #{cid} [{clause['contract_type']}]: reject thin stub")
            if not dry_run:
                snapshot_before("b4", clause)
                bulk_review(cid, "rejected")
                record_applied("b4", clause, {"tag_review": "bulk rejected"},
                               "thin stub triage")
            stats["applied"] += 1
            continue
        # rewrite
        new_body = (new_body or "").strip()
        if not new_body or new_body == (clause.get("body") or "").strip():
            print(f"  b4 #{cid}: DRAFT REJECTED (empty/identical)")
            stats["rejected_drafts"] += 1
            continue
        print(f"  b4 #{cid} [{clause['contract_type']}]: apply fix")
        if not dry_run:
            snapshot_before("b4", clause)
            update_clause(cid, {"body": new_body})
            record_applied("b4", clause, {"body": new_body},
                           "curated spot fix")
        stats["applied"] += 1
    return stats


# --------------------------------------------------------------------------- #
# rollback
# --------------------------------------------------------------------------- #
def run_rollback(batch: str, dry_run: bool) -> int:
    manifest = load_manifest(batch)
    before_dir = REMEDIATION_DIR / batch / "before"
    applied_ids = set(manifest.get("applied_ids") or [])
    snaps = sorted(p for p in before_dir.glob("*.json")
                   if p.stem in applied_ids or not applied_ids)
    if not snaps:
        raise SystemExit(f"no before-snapshots under {before_dir}")
    print(f"rollback {batch}: {len(snaps)} snapshots "
          f"(manifest applied={len(manifest.get('applied_ids', []))})")
    restored = 0
    for p in snaps:
        before = json.loads(p.read_text(encoding="utf-8"))
        cid = before["id"]
        if dry_run:
            print(f"  [dry-run] would restore #{cid}")
            restored += 1
            continue
        current = get_clause_row(cid)
        if current is None:
            print(f"  ⚠ #{cid} no longer exists, skipping")
            continue
        changed = False
        if (current.get("body") or "") != (before.get("body") or ""):
            update_clause(cid, {"body": before["body"]})
            changed = True
        cur_review = current.get("tag_review") or {}
        before_review = before.get("tag_review") or {}
        if cur_review != before_review:
            set_tag_review(cid, before_review)
            changed = True
        if changed:
            print(f"  ✓ restored #{cid} [{before['contract_type']}]")
            restored += 1
    print(f"rollback {batch}: {restored} clauses restored")
    return 0


# --------------------------------------------------------------------------- #
# listing / main
# --------------------------------------------------------------------------- #
def list_batches(clauses: list[dict]) -> None:
    b0 = len(select_b0())
    b1 = len(select_b1())
    b3 = sum(
        1 for c in clauses
        if (c.get("body") or "")
        and (c.get("section") or "") not in SIGN_SECTION_WHITELIST
        and strip_artifacts(c)[0] is not None
    )
    print(f"b0-data: {b0} clauses with `_` metadata keys in tag_review")
    print(f"b1:      {b1} duplicate victims (tagged body_hash groups)")
    print(f"b2:      {len(B2_IDS)} region targets "
          f"({len([i for i in B2_EXEMPT_IDS if i in B2_IDS])} exempt), needs --drafts")
    print(f"b3:      {b3} clauses with strippable artifacts "
          f"(sign-section whole-block clauses excluded)")
    print("b4:      curated set, needs --drafts")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--database-url", default=None,
                    help="override database_url (e.g. port-forward DSN)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="show per-batch scope")
    g.add_argument("--batch", choices=["b0-data", "b1", "b2", "b3", "b4"])
    g.add_argument("--rollback", metavar="BATCH")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--drafts", default=None,
                    help="JSON file {id: body|{action,body}} for b2/b4")
    args = ap.parse_args()

    if args.database_url:
        os.environ["database_url"] = args.database_url
        os.environ["DATABASE_URL"] = args.database_url

    if args.rollback:
        return run_rollback(args.rollback, args.dry_run)

    clauses = load_all_clauses()
    clauses_by_id = {c["id"]: c for c in clauses}

    if args.list:
        list_batches(clauses)
        return 0

    drafts: dict = {}
    if args.batch in ("b2", "b4"):
        if not args.drafts:
            raise SystemExit(f"--batch {args.batch} requires --drafts FILE")
        drafts = json.loads(Path(args.drafts).read_text(encoding="utf-8"))

    if args.batch == "b0-data":
        stats = run_b0(clauses_by_id, args.dry_run, args.limit)
    elif args.batch == "b1":
        stats = run_b1(select_b1(), clauses_by_id, args.dry_run, args.limit)
    elif args.batch == "b2":
        stats = run_b2(drafts, clauses_by_id, args.dry_run, args.limit)
    elif args.batch == "b3":
        stats = run_b3(clauses, args.dry_run, args.limit)
    else:
        stats = run_b4(drafts, clauses_by_id, args.dry_run)

    print(f"batch {args.batch}: {stats}")
    if not args.dry_run:
        write_manifest(
            args.batch,
            dry_run=False,
            stats=stats,
            drafts_file=args.drafts,
            applied_ids=sorted(
                p.stem for p in (batch_dir(args.batch) / "applied").glob("*.json")
            ),
        )
        print(f"manifest -> {batch_dir(args.batch) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
