#!/usr/bin/env python3
"""Clause-library audit driver: classify -> rewrite -> verify -> persist.

Runs :mod:`src.clauses.audit` over assembly-ready clauses (P0 base / P1
custom / P2 tagged-ready) to fix region leakage, missing slots, and
extraction artifacts. Also provides a deterministic dedupe pass (P3) that
rejects exact ``body_hash`` duplicates — no LLM.

Mirrors ``scripts/self_iterate.py`` (load_dotenv override, relay retry,
file reports). Concurrency: ``AUDIT_MAX_WORKERS`` outer pool × 3 inner
classify models = 12 concurrent LLM calls (relay ceiling). DB writes are
serial (``update_clause`` goes through the shared connection, which is not
thread-safe) — LLM work fans out, persistence does not.

Usage::

    # dry-run the employment pilot (4 base clauses) first
    python scripts/audit_clauses.py --tier p0 --type employment --dry-run

    # apply
    python scripts/audit_clauses.py --tier p0 --type employment

    # full P0-P2 run across all 43 types (~40-60 min)
    python scripts/audit_clauses.py --tier all

    # deterministic dedupe (no LLM)
    python scripts/audit_clauses.py --tier p3
"""

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

# override=True: the launching shell often exports OPENAI_API_KEY /
# OPENAI_API_BASE as EMPTY strings; load_dotenv's default override=False
# then treats them as "already set" and skips them — leaving litellm with
# no credentials. Mirrors scripts/self_iterate.py.
load_dotenv(override=True)
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

from src.clauses.audit import audit_one_clause, region_lint
from src.clauses.store import list_clauses, update_clause
from src.clauses.tag_review import bulk_review, is_assembly_ready
from src.contracts.templates import list_contract_types
from src.eval.db import connect

# Outer concurrency. Each audit_one_clause() spawns an inner 3-thread trio
# for the classify vote, so peak concurrent LLM calls = AUDIT_MAX_WORKERS × 3.
# Relay rate-limits per uid at 12 concurrent (probe 2026-08-11: 12 ok, 16 =
# 429s). 4 × 3 = 12 — right at the clean ceiling. Drop to 3 if 429s appear.
AUDIT_MAX_WORKERS = int(os.environ.get("AUDIT_MAX_WORKERS", "4"))

TIER_CATEGORY = {"p0": "base", "p1": "custom", "p2": "tagged"}
VERDICT_KEYS = (
    "ok", "region_leak", "missing_slot", "wrong_scenario",
    "extraction_artifact", "duplicate", "uncertain",
)


# --------------------------------------------------------------------------- #
# clause loading
# --------------------------------------------------------------------------- #
def load_audit_clauses(contract_type: str, tier: str) -> list[dict]:
    """Load the clauses that enter assembly for a (type, tier).

    - P0 base: all with non-empty body (assembly uses base as fallback,
      no readiness gate).
    - P1 custom: only ``is_assembly_ready`` customs (assembly gates custom
      on tag_review all-approved).
    - P2 tagged: all with non-empty body, EXCEPT clauses already rejected
      by the P3 dedupe pass (they're dupes of a canonical being audited).
      Assembly does not currently gate tagged on readiness, but rejected
      dupes are noise — skip them.
    """
    cat = TIER_CATEGORY[tier]
    clauses = list_clauses(contract_type, category=cat)
    if tier == "p1":
        return [c for c in clauses if is_assembly_ready(c)]
    if tier == "p2":
        # Only scenario-bearing tagged clauses enter assembly: ``_select_clauses``
        # (src/clauses/assemble.py) loads tagged ONLY when a scenario is set,
        # filtered by ``tags={"scenario": scenario}``. The 4712 scenario-less
        # tagged clauses never surface in a generated contract, so LLM-auditing
        # them for region_leak/missing_slot is wasted spend. They are handled
        # separately (P3 dedupe already rejected exact dupes; a census of the
        # remainder is reported to the user for an orphan/retag decision).
        return [
            c for c in clauses
            if (c.get("body") or "").strip()
            and not any(v == "rejected" for v in (c.get("tag_review") or {}).values())
            and (c.get("tags") or {}).get("scenario")
        ]
    return [c for c in clauses if (c.get("body") or "").strip()]


def lint_baseline(clauses: list[dict]) -> dict:
    """Run :func:`region_lint` over a clause set (deterministic, no LLM)."""
    total = 0
    per_clause = []
    for c in clauses:
        hits = region_lint(c.get("body") or "")
        if hits:
            total += len(hits)
            per_clause.append({"id": c["id"], "section": c.get("section"), "matches": hits})
    return {"total_clauses": len(clauses), "total_matches": total, "per_clause": per_clause}


# --------------------------------------------------------------------------- #
# audit batch
# --------------------------------------------------------------------------- #
def _audit_clause_task(clause: dict) -> dict:
    """Wrap audit_one_clause so one bad clause doesn't kill the batch."""
    try:
        return audit_one_clause(clause)
    except Exception as e:
        return {
            "clause_id": clause.get("id"),
            "contract_type": clause.get("contract_type"),
            "section": clause.get("section"),
            "verdict": "uncertain",
            "confidence": 0.0,
            "original": clause.get("body"),
            "rewritten": None,
            "applied": False,
            "verify": None,
            "model_verdicts": {},
            "region_lint_before": region_lint(clause.get("body") or ""),
            "region_lint_after": [],
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def _tally_resumed(stats: dict, result: dict) -> None:
    """Fold a previously-persisted result file into stats (no DB write, no LLM).

    ``applied`` clauses were already written to the DB in the prior run, so we
    only count them here — never re-call ``update_clause``.
    """
    v = result.get("verdict", "uncertain")
    stats[v if v in stats else "uncertain"] += 1
    if result.get("error"):
        stats["errors"] += 1
    stats["region_lint_after"] += len(result.get("region_lint_after") or [])
    if result.get("applied"):
        stats["applied"] += 1
    elif v in ("region_leak", "missing_slot", "extraction_artifact"):
        stats["verify_failed"] += 1


def _tally_fresh(
    stats: dict, result: dict, clause: dict, dry_run: bool, applied: list[dict]
) -> None:
    """Fold a freshly-audited result into stats + persist the rewrite (serial)."""
    v = result.get("verdict", "uncertain")
    stats[v if v in stats else "uncertain"] += 1
    if result.get("error"):
        stats["errors"] += 1
    stats["region_lint_after"] += len(result.get("region_lint_after") or [])

    # Persist rewrite (serial — update_clause uses the shared conn).
    if result.get("applied") and result.get("rewritten"):
        if dry_run:
            print(f"    [dry-run] would update id={clause['id']} ({v})")
        else:
            try:
                update_clause(clause["id"], {"body": result["rewritten"]})
                result["persisted"] = True
                stats["applied"] += 1
                applied.append({
                    "clause_id": clause["id"],
                    "section": clause.get("section"),
                    "verdict": v,
                })
                print(f"    ✅ updated id={clause['id']} ({v})")
            except Exception as e:
                result["persisted"] = False
                result["persist_error"] = str(e)
                print(f"    ⚠ persist failed id={clause['id']}: {e}")
    elif v in ("region_leak", "missing_slot", "extraction_artifact") and not result.get("applied"):
        stats["verify_failed"] += 1
        print(f"    ✗ keep id={clause['id']} ({v}: verify failed / no change)")


def run_audit_batch(
    contract_type: str,
    tier: str,
    clauses: list[dict],
    dry_run: bool,
    audit_dir: Path,
    workers: int,
) -> tuple[dict, list[dict]]:
    """Audit a batch concurrently; persist rewrites + result files serially.

    Resume-safe: clauses with an existing ``output/audit/<type>_<id>.json`` are
    tallied from disk (no LLM, no DB write) so a re-run after a kill picks up
    exactly where it left off. Only clauses without a result file are audited.
    """
    stats = {k: 0 for k in VERDICT_KEYS}
    stats.update({
        "audited": 0, "applied": 0, "verify_failed": 0, "errors": 0,
        "region_lint_before": 0, "region_lint_after": 0, "resumed": 0,
    })
    applied_rewrites: list[dict] = []

    lb = lint_baseline(clauses)
    stats["region_lint_before"] = lb["total_matches"]
    print(f"  [lint] {contract_type}/{tier}: {lb['total_matches']} residual region "
          f"matches in {lb['total_clauses']} clauses")

    # Split into already-audited (resume from disk) and to-audit (fresh LLM).
    to_audit: list[dict] = []
    for c in clauses:
        rp = audit_dir / f"{contract_type}_{c['id']}.json"
        if rp.exists():
            try:
                result = json.loads(rp.read_text(encoding="utf-8"))
            except Exception:
                result = None
            if result and "verdict" in result:
                _tally_resumed(stats, result)
                stats["resumed"] += 1
                continue
        to_audit.append(c)

    if to_audit:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_audit_clause_task, c): c for c in to_audit}
            for fut in as_completed(futures):
                clause = futures[fut]
                result = fut.result()
                stats["audited"] += 1
                _tally_fresh(stats, result, clause, dry_run, applied_rewrites)
                # Result file (always — audit trail + rollback source).
                rp = audit_dir / f"{contract_type}_{clause['id']}.json"
                rp.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
    else:
        print(f"  [resume] all {len(clauses)} clauses already audited, skipping LLM")

    return stats, applied_rewrites


def persist_audit_run(contract_type: str, tier: str, stats: dict, applied: list[dict]) -> None:
    """Best-effort: record the audit batch to ``pipeline_runs`` for the dashboard.

    The dashboard reads ONLY ``pipeline_runs``; without this row the audit is
    invisible online. Never let a DB hiccup kill the run — swallow all errors.
    """
    try:
        from src.eval.pipeline_store import insert_pipeline_run

        pid = insert_pipeline_run({
            "contract_type": contract_type,
            "tags": {"source": "clause_audit", "tier": tier},
            "stance": None,
            # rubric_name is NOT NULL in the schema; use a sentinel (this is
            # an audit batch, not a rubric-evaluated run).
            "rubric_name": "clause_audit",
            "task_desc": (
                f"Clause audit {tier} ({contract_type}): "
                f"{stats['applied']}/{stats['audited']} rewrites applied"
            ),
            "score": stats["applied"],
            "max_score": stats["audited"],
            "n_passed": stats["applied"],
            "n_criteria": stats["audited"],
            "all_pass": 1 if stats["errors"] == 0 else 0,
            "iteration": 1,
            "actions_taken": applied,
        })
        print(f"  📊 pipeline_runs id={pid}")
    except Exception as e:
        print(f"  ⚠ pipeline_runs persist failed (non-fatal): {e}")


# --------------------------------------------------------------------------- #
# resume support
# --------------------------------------------------------------------------- #
def _batch_already_run(contract_type: str, tier: str) -> bool:
    """True if a completed ``clause_audit`` row exists for ``(type, tier)``.

    ``persist_audit_run`` writes the pipeline_runs row only at the END of a
    finished batch, so its presence means the batch completed cleanly. A batch
    killed mid-run has no row and will re-run — which is safe, because any
    rewrites already applied produced clean bodies that re-classify as ``ok``
    (the verify gate + deterministic region_lint prevent double-rewrites).
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM pipeline_runs "
            "WHERE contract_type = %s "
            "  AND tags->>'source' = 'clause_audit' "
            "  AND tags->>'tier' = %s "
            "LIMIT 1",
            (contract_type, tier),
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# audit (P0-P2)
# --------------------------------------------------------------------------- #
def run_audit(args) -> int:
    types = [args.contract_type] if args.contract_type else [t["key"] for t in list_contract_types()]
    tiers = ["p0", "p1", "p2"] if args.tier == "all" else [args.tier]
    audit_dir = Path("output/audit")
    audit_dir.mkdir(parents=True, exist_ok=True)

    grand = {k: 0 for k in VERDICT_KEYS}
    grand.update({"audited": 0, "applied": 0, "verify_failed": 0, "errors": 0,
                  "region_lint_before": 0, "region_lint_after": 0})

    for ct in types:
        for tier in tiers:
            clauses = load_audit_clauses(ct, tier)
            if args.limit:
                clauses = clauses[:args.limit]
            if not clauses:
                print(f"\n{ct}/{tier}: 0 clauses, skipping")
                continue

            # A full (non-scoped, non-dry) run skips types whose batch already
            # completed — persist_audit_run writes the pipeline_runs row only at
            # the END of a clean batch, so its presence means the batch finished.
            # Resume-safe result files still backstop a single-type re-run.
            if not args.dry_run and not args.contract_type and _batch_already_run(ct, tier):
                print(f"\n{ct}/{tier}: already audited (pipeline_runs row exists), skipping")
                continue

            print(f"\n{'=' * 60}")
            print(f"{ct}/{tier}: {len(clauses)} clauses"
                  f"{' (dry-run)' if args.dry_run else ''}")
            print(f"{'=' * 60}")

            t0 = time.time()
            stats, applied = run_audit_batch(
                ct, tier, clauses, args.dry_run, audit_dir, args.workers,
            )
            elapsed = time.time() - t0

            print(f"\n  {ct}/{tier} done in {elapsed:.0f}s: "
                  f"audited={stats['audited']} ok={stats['ok']} "
                  f"region_leak={stats['region_leak']} missing_slot={stats['missing_slot']} "
                  f"artifact={stats['extraction_artifact']} applied={stats['applied']} "
                  f"verify_failed={stats['verify_failed']} errors={stats['errors']}")
            print(f"  region_lint: {stats['region_lint_before']} -> "
                  f"{stats['region_lint_after']} matches")

            if not args.dry_run:
                persist_audit_run(ct, tier, stats, applied)

            for k in grand:
                grand[k] += stats.get(k, 0)

    print(f"\n{'=' * 60}")
    print(f"GRAND TOTAL: audited={grand['audited']} applied={grand['applied']} "
          f"region_lint={grand['region_lint_before']}->{grand['region_lint_after']}")
    print(f"  verdicts: ok={grand['ok']} region_leak={grand['region_leak']} "
          f"missing_slot={grand['missing_slot']} artifact={grand['extraction_artifact']} "
          f"wrong_scenario={grand['wrong_scenario']} duplicate={grand['duplicate']} "
          f"uncertain={grand['uncertain']}")
    return 0


# --------------------------------------------------------------------------- #
# dedupe (P3, no LLM)
# --------------------------------------------------------------------------- #
def run_dedupe(args) -> int:
    """Deterministic dedupe: reject exact ``body_hash`` dupes, keep lowest id.

    Pure SQL + ``bulk_review(reject)``. Idempotent: already-rejected clauses
    are filtered out before grouping, so re-runs are no-ops. Recoverable via
    re-approval. No LLM cost.

    NOTE: for rejected tagged clauses to actually drop from assembly,
    ``_select_clauses`` in ``src/clauses/assemble.py`` must filter the tagged
    path by ``is_assembly_ready`` — a one-line change made alongside this pass.
    Without it, ``_pick_variant`` still deduplicates by picking one per section,
    so assembly output is unaffected; the rejection primarily cleans RAG search
    and heuristic-tiebreak noise.
    """
    types = [args.contract_type] if args.contract_type else [t["key"] for t in list_contract_types()]
    total_groups = 0
    total_rejected = 0

    for ct in types:
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT body_hash, array_agg(id ORDER BY id) AS ids "
                "FROM clauses "
                "WHERE tags->>'source' = 'tagged' "
                "  AND body_hash IS NOT NULL "
                "  AND contract_type = %s "
                "  AND NOT EXISTS ("
                "    SELECT 1 FROM jsonb_each_text(tag_review) WHERE value = 'rejected'"
                "  ) "
                "GROUP BY body_hash HAVING count(*) > 1",
                (ct,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            continue

        print(f"\n{ct}: {len(rows)} dup groups")
        for r in rows:
            ids = r["ids"]
            canonical = ids[0]
            total_groups += 1
            for did in ids[1:]:
                if args.dry_run:
                    print(f"  [dry-run] reject id={did} (dup of {canonical})")
                else:
                    bulk_review(did, "rejected")
                    print(f"  ✅ rejected id={did} (dup of {canonical})")
                total_rejected += 1

    print(f"\n{'=' * 60}")
    print(f"DEDUPE: {total_groups} groups, {total_rejected} clauses rejected "
          f"({'dry-run' if args.dry_run else 'applied'})")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--tier", required=True, choices=["p0", "p1", "p2", "p3", "all"],
        help="P0=base, P1=custom, P2=tagged-ready, P3=dedupe (no LLM), all=P0+P1+P2",
    )
    ap.add_argument(
        "--type", dest="contract_type", default=None,
        help="Scope to one contract type (default: all 43)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print verdicts/rewrites + write result files, but do NOT update the DB",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="Cap clauses per type/tier (for testing)",
    )
    ap.add_argument(
        "--workers", type=int, default=AUDIT_MAX_WORKERS,
        help=f"Outer concurrency (default {AUDIT_MAX_WORKERS}; ×3 classify = 12 at relay ceiling)",
    )
    args = ap.parse_args()

    if args.tier == "p3":
        return run_dedupe(args)
    return run_audit(args)


if __name__ == "__main__":
    raise SystemExit(main())
