"""Domain-neutral flywheel export machine (per-pack Judge/Drafter datasets).

The finetune flywheel turns curated knowledge into training datasets:

- **Judge** sets — labeled samples (``purpose='ground_truth'``) used to train
  or verify a judge model;
- **Drafter** sets — generation samples used as SFT warm-up
  (``purpose='sft_warmup'``, silver-eligible) or as reward-positive samples
  (``purpose='reward_positive'``, gold-only).

This module generalizes the vertical-specific exporters that live in
``scripts/finetune/`` (which assumed one hard-coded material shape): a domain
pack declares its exportable material as ``kind`` strings, and every record —
either pulled from :mod:`src.bench.store` knowledge units or injected by a
caller-supplied ``extract_fn`` — carries one of the four provenance tiers.
ALL tier decisions route through the single-point guards in
:mod:`src.bench.tiers`; there is no second implementation here.

Two tracks, mirroring the existing pipelines' semantics:

- **Labeled purposes** (``ground_truth`` / ``reward_positive`` and their
  aliases; any unknown purpose is treated as labeled — fail closed): the
  output set is gold-only, and the guard runs over the WHOLE material pool,
  so a pool containing forbidden machine material aborts the export loudly
  (:class:`src.bench.tiers.TierGuardError`) instead of silently dropping the
  rows. :func:`assert_not_ground_truth` rejects bronze for ground truth and
  bronze+silver for reward positives (tiers' own error semantics); a
  gold-only check then rejects any remaining non-gold tier for the same
  purpose with the same exception type.
- **Warm-up purposes** (``sft_warmup`` / ``warmup``): no label or reward
  claim, so a mixed pool is legal and :func:`filter_by_tier` is the single
  gate. Default floor is ``silver``: gold+silver only, never bronze/raw —
  the same warm-start semantics as the vertical pipelines.

Every exported JSONL row embeds ``tier`` and a ``provenance`` block carrying
a ``source_ref`` back-pointer (plus ``unit_id`` for store-sourced rows), so
any sample resolves back to the material it came from. Output is
deterministic (fixed sort + canonical JSON with sorted keys), so re-exporting
over the same material produces a byte-identical file (idempotent export).

Zero LLM, zero network, standard library + kernel modules only. The kernel
never imports or reads a domain pack (enforced by
``tests/test_kernel_domain_free.py``); domain adaptation happens either at the
call site (inject ``extract_fn``) or in the scripts-layer CLI
``scripts/finetune/export_by_pack.py``.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Callable, Iterable, Optional

from .store import list_knowledge_units
from .tiers import (
    TIERS,
    TierGuardError,
    assert_not_ground_truth,
    filter_by_tier,
)

__all__ = [
    "GOLD",
    "WARMUP_PURPOSES",
    "DEFAULT_WARMUP_FLOOR",
    "export_dataset",
]

# The only tier a labeled (ground-truth / reward-positive) set may contain.
GOLD = "gold"

# Purposes that carry no label/reward claim: tier floor filtering only, no
# gold-only requirement. Anything NOT listed is treated as a labeled purpose
# and runs the fail-loud single-point guard (fail closed).
WARMUP_PURPOSES = frozenset({"sft_warmup", "warmup"})

# Warm-up default: silver-and-above (gold+silver), matching the pipelines'
# warm-start semantics (never bronze/raw material).
DEFAULT_WARMUP_FLOOR = "silver"


def _dumps(record: dict) -> str:
    """Canonical one-line JSON (sorted keys, fixed separators).

    Same-bytes-for-same-record is what makes re-exports byte-identical.
    """
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_record(rec: dict, kind: str) -> dict:
    """Validate and normalize one material record into the common shape.

    Required: ``tier`` in :data:`src.bench.tiers.TIERS`. Identity falls back
    to ``id``, then a body hash, so provenance can always back-point.
    """
    if not isinstance(rec, dict):
        raise ValueError(f"material for kind={kind!r}: expected dict records, got {type(rec).__name__}")
    tier = rec.get("tier")
    if tier not in TIERS:
        raise ValueError(
            f"material for kind={kind!r}: invalid tier {tier!r} "
            f"(expected one of {list(TIERS)}; see src.bench.tiers)"
        )
    body = rec.get("body")
    body = "" if body is None else str(body)
    external_key = rec.get("external_key")
    if external_key is None:
        external_key = rec.get("id")
    if external_key is None:
        # Anonymous injected record: stable content hash keeps exports deterministic.
        external_key = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return {
        "kind": str(rec.get("kind") or kind),
        "namespace": str(rec.get("namespace") or "default"),
        "external_key": str(external_key),
        "body": body,
        "tags": rec.get("tags") or {},
        "attrs": rec.get("attrs") or {},
        "tier": str(tier),
        "source_path": rec.get("source_path"),
        "unit_id": rec.get("id"),
        "provenance": dict(rec.get("provenance") or {}),
    }


def _collect_material(
    conn: Any,
    kind: str,
    extract_fn: Optional[Callable[[str], Iterable[dict]]],
    limit: int,
) -> list[dict]:
    """Fetch the material pool: injected adapter first, else knowledge units."""
    if extract_fn is not None:
        return list(extract_fn(kind))
    if conn is None:
        raise ValueError(
            "export_dataset needs a store connection when no extract_fn is injected"
        )
    units = list_knowledge_units(conn, kind=kind, limit=limit)
    # store lists by updated_at desc; sort by id for deterministic exports.
    return sorted(units, key=lambda u: u["id"])


def _guard_labeled_pool(records: list[dict], purpose: str) -> None:
    """Single-point guard over the WHOLE pool for labeled purposes.

    1. :func:`src.bench.tiers.assert_not_ground_truth` — tiers' own semantics
       (bronze never ground truth; bronze+silver never reward positive).
    2. Gold-only rule — any remaining non-gold tier in a pool being
       assembled as a labeled set is an assembly error: raise, do not drop.
       Same exception type and message shape, extending tiers' fail-loud
       semantics to the silver/raw corner of ground-truth assembly.
    """
    for rec in records:
        assert_not_ground_truth(rec["tier"], purpose=purpose)
        if rec["tier"] != GOLD:
            raise TierGuardError(
                f"tier={rec['tier']!r} cannot be used for purpose={purpose!r}: "
                f"labeled flywheel datasets are gold-only; the material pool "
                f"must not contain {rec['tier']!r} rows. See src.bench.tiers."
            )


def _export_row(rec: dict, *, pack: str, purpose: str, floor: str) -> dict:
    """Build the JSONL row: full record + tier + provenance back-pointer."""
    prov = dict(rec["provenance"])
    prov.update(
        {
            "pack": pack,
            "kind": rec["kind"],
            "namespace": rec["namespace"],
            "external_key": rec["external_key"],
            "purpose": purpose,
            "tier_floor": floor,
            "source_ref": f"{rec['namespace']}/{rec['kind']}/{rec['external_key']}",
        }
    )
    if rec.get("unit_id") is not None:
        prov["unit_id"] = rec["unit_id"]
    if rec.get("source_path"):
        prov.setdefault("source_path", rec["source_path"])
    row = {k: v for k, v in rec.items() if k != "unit_id"}
    row["provenance"] = prov
    return row


def export_dataset(
    conn: Any,
    *,
    pack: str,
    kind: str,
    purpose: str = "ground_truth",
    tier_floor: Optional[str] = None,
    out_path: Any,
    extract_fn: Optional[Callable[[str], Iterable[dict]]] = None,
    limit: int = 10000,
) -> dict:
    """Export one domain pack's dataset for ``kind`` + ``purpose`` as JSONL.

    Parameters
    ----------
    conn
        Store connection (psycopg, any row factory store accepts). Ignored
        when ``extract_fn`` is injected (may be ``None`` then).
    pack
        Domain pack name — an opaque tag embedded in every row's provenance.
        The kernel never resolves it to a directory.
    kind
        The knowledge-unit kind whose material is exported.
    purpose
        ``'ground_truth'`` / ``'reward_positive'`` (labeled: gold-only,
        fail-loud guard over the pool; unknown purposes are treated as
        labeled, fail closed) or ``'sft_warmup'`` / ``'warmup'`` (warm-up:
        tier-floor filtered, silver-and-above by default).
    tier_floor
        Explicit rank cutoff (``'gold'``/``'silver'``/``'bronze'``/``'raw'``).
        Optional for warm-up (defaults to ``'silver'``); for labeled
        purposes it may only be omitted or ``'gold'`` — anything else is a
        request-level ``ValueError``.
    out_path
        Destination JSONL file (parents created; overwritten deterministically).
    extract_fn
        Domain adapter: ``kind -> Iterable[record]``. Each record needs a
        valid ``tier``; ``body``/``namespace``/``external_key``/``tags``/
        ``attrs``/``source_path``/``provenance`` optional. Injected exporters
        let a pack source material from its own tables instead of knowledge
        units.
    limit
        Row cap for the default knowledge-units loader (ignored by adapters).

    Returns a summary dict: pool/exported counts, per-tier counts, effective
    floor, out_path.

    Raises
    ------
    src.bench.tiers.TierGuardError
        Labeled purpose and the pool contains a forbidden tier (tiers'
        semantics) or any non-gold tier (gold-only rule).
    ValueError
        Invalid tier on a material record, unknown ``tier_floor``, or a
        labeled request asking for a sub-gold floor.
    """
    pack, kind, purpose = str(pack), str(kind), str(purpose)
    out_path = pathlib.Path(out_path)

    warmup = purpose in WARMUP_PURPOSES
    if warmup:
        floor = tier_floor or DEFAULT_WARMUP_FLOOR
        if floor not in TIERS:
            raise ValueError(
                f"tier_floor={tier_floor!r} is not a valid tier "
                f"(expected one of {list(TIERS)}; see src.bench.tiers)"
            )
    else:
        if tier_floor not in (None, GOLD):
            raise ValueError(
                f"tier_floor={tier_floor!r} is not valid for labeled purpose="
                f"{purpose!r}: labeled exports are gold-only (see src.bench.tiers)"
            )
        floor = GOLD

    material = _collect_material(conn, kind, extract_fn, limit)
    records = [_normalize_record(r, kind) for r in material]

    if warmup:
        # filter_by_tier is the single-point rank gate: gold-side only.
        selected = filter_by_tier(records, floor)
    else:
        # Fail loud over the whole pool, then the same rank gate at gold.
        _guard_labeled_pool(records, purpose)
        selected = filter_by_tier(records, floor)

    rows = [_export_row(r, pack=pack, purpose=purpose, floor=floor) for r in selected]
    rows.sort(key=lambda r: (r["namespace"], r["external_key"], r["body"]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_dumps(r) for r in rows]
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    tiers = {t: sum(1 for r in rows if r["tier"] == t) for t in TIERS}
    return {
        "pack": pack,
        "kind": kind,
        "purpose": purpose,
        "tier_floor": floor,
        "out_path": str(out_path),
        "pool": len(records),
        "exported": len(rows),
        "tiers": tiers,
    }
