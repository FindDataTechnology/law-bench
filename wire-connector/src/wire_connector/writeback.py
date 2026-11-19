"""Gold → wire writeback through the REAL writable surface (no pretense).

What fd-wire's entity API accepts (refreshed 2026-11-05 for
add-entity-bench-contract 0050):

- ``PUT /api/v1/entities/{id}`` — full replacement of ``EntityCreateIn``,
  now WITH first-class ``tier``/``sensitivity`` (vocabulary validated
  upstream). The metadata-bag stamp (``column_notes["_bench"]``) is still
  written alongside: it carries the reviewer/idempotency provenance that the
  two first-class fields don't, and keeps pre-0050 consumers working.
- relationships: POST (declare) / DELETE / **PUT update face (0050 NEW)**
  ``{label, tier, sensitivity}`` (three keys required, explicit null=clear).
  Gold RELATION writeback now uses the update face — the old
  "delete + redeclare" and the honest-refusal path are both gone.

Idempotency: the kernel (``run_writeback`` in the public promotion machine)
skips units already marked written-back — the wire key ``wire/<kind>/<id>`` is
the idempotency key, no double-push, no duplicate rows upstream.

Batch discipline (close-wire-real-loop design D3, task 1.2): writebacks are
operator-approved batch actions. ``run_writeback_confirmed`` previews the
exact pending batch (gold, reviewer-attributed, not-yet-written-back) and
requires an explicit confirmation before ANY network write — interactive
stdin prompt by default, or inject a ``confirm callable`` for scripted use.

Failure posture (contract: 回写失败不误标「已回写」): any exception from the
client propagates up; the kernel records the unit as NOT written back,
continues with the rest of the batch, and reports the error per unit.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from .client import WireClient, WireClientError

#: reserved key in wire's column_notes metadata bag carrying the bench stamp
BENCH_NOTE_KEY = "_bench"

#: machine-readable provenance that rides the bag alongside the first-class
#: fields (reviewer / idempotency key / review timestamp)


def format_bench_stamp(payload: dict) -> str:
    """Machine-readable one-string stamp (parsed by wire-side consumers)."""
    review = payload.get("review") or {}
    parts = [
        "platform=knowledge-bench",
        f"tier={payload.get('tier', 'gold')}",
        f"sensitivity={payload.get('sensitivity', 'internal')}",
        f"idempotency_key={payload.get('idempotency_key', '')}",
    ]
    if review.get("reviewer"):
        parts.append(f"reviewer={review['reviewer']}")
    if review.get("at"):
        parts.append(f"review_at={review['at']}")
    return "; ".join(parts)


class WireWriteback:
    """``writeback_fn`` for the kernel's ``run_writeback``.

    Usage::

        from src.bench import promotion
        from wire_connector.writeback import WireWriteback
        promotion.run_writeback(conn, "wire", WireWriteback(client))
    """

    def __init__(self, client: Any = None) -> None:
        self.client = client or WireClient()

    def __call__(self, payload: dict) -> dict:
        kind = payload.get("kind")
        if kind == "entity":
            return self._write_entity(payload)
        if kind == "relation":
            return self._write_relation(payload)
        raise WireClientError(f"unknown payload kind {kind!r}")

    def _write_entity(self, payload: dict) -> dict:
        node = payload.get("registry_fields") or {}
        # rebuild the full-replacement body from the mirrored snapshot
        # (wire identity master semantics: PUT revalidates the whole row)
        ds = node.get("dataset") or {}
        dataset_id = ds.get("id")
        if not dataset_id or not node.get("pk_columns") or not node.get("name"):
            raise WireClientError(
                "mirrored node snapshot lacks name/dataset.id/pk_columns — "
                "refusing to write a half-replacement; re-sync first"
            )
        notes = dict(node.get("column_notes") or {})
        notes[BENCH_NOTE_KEY] = format_bench_stamp(payload)
        resp = self.client.update_entity(
            int(payload["external_key"]),
            name=node["name"],
            dataset_id=str(dataset_id),
            pk_columns=list(node["pk_columns"]),
            description=node.get("description"),
            display_column=node.get("display_column"),
            column_notes=notes,
            # 0050 first-class fields — the contract's real demand
            tier=payload.get("tier", "gold"),
            sensitivity=payload.get("sensitivity", "internal"),
        )
        receipt = {
            "endpoint": f"PUT /api/v1/entities/{payload['external_key']}",
            "wire_updated_at": (resp or {}).get("updated_at"),
            "stamp_key": BENCH_NOTE_KEY,
            "first_class_fields": ["tier", "sensitivity"],
        }
        # carry the idempotency key in the receipt for full traceability
        receipt["idempotency_key"] = payload.get("idempotency_key")
        return receipt

    def _write_relation(self, payload: dict) -> dict:
        edge = payload.get("registry_fields") or {}
        rel_id = edge.get("id")
        from_entity_id = edge.get("from_entity_id")
        if rel_id is None or from_entity_id is None:
            raise WireClientError(
                "mirrored edge snapshot lacks id/from_entity_id — refusing to "
                "update a relationship without an addressable identity; "
                "re-sync first"
            )
        resp = self.client.update_relationship(
            int(from_entity_id),
            int(rel_id),
            label=edge.get("label"),
            # 0050 update face: the three keys are required (explicit null =
            # clear); tier/sensitivity come from the promotion payload
            tier=payload.get("tier", "gold"),
            sensitivity=payload.get("sensitivity", "internal"),
        )
        receipt = {
            "endpoint": (
                f"PUT /api/v1/entities/{from_entity_id}"
                f"/relationships/{rel_id}"
            ),
            "wire_updated": resp is not None,
            "first_class_fields": ["label", "tier", "sensitivity"],
        }
        receipt["idempotency_key"] = payload.get("idempotency_key")
        return receipt


#: kernel loader indirection (test/selfcheck seam — hermetic runs inject a
#: stand-in kernel without touching sys.path or a PG connection)
_kernel_loader: Optional[Callable[[], Any]] = None


def _load_kernel() -> Any:
    loader = _kernel_loader or _default_kernel_loader
    return loader()


def _default_kernel_loader() -> Any:
    from .sync import import_kernel

    return import_kernel()


def pending_batch(conn: Any, namespace: str = "wire", *, limit: int = 1000) -> list[dict]:
    """The exact batch a writeback run WOULD push (gold, reviewer-attributed,
    not-yet-written-back) — the preview surface for operator confirmation."""
    promotion = _load_kernel()
    payloads = promotion.export_gold(conn, namespace, limit=limit)
    return [p for p in payloads if not p.get("written_back")]


def format_batch_preview(batch: list[dict]) -> str:
    """Human-readable batch summary (bounded: kind/key/sensitivity/reviewer)."""
    lines = [f"pending writeback batch: {len(batch)} unit(s)"]
    for payload in batch:
        review = payload.get("review") or {}
        lines.append(
            f"  - {payload['kind']} {payload['external_key']} "
            f"sensitivity={payload.get('sensitivity', 'internal')} "
            f"reviewer={review.get('reviewer', '(none)')}"
        )
    return "\n".join(lines)


def _default_confirm(batch: list[dict]) -> bool:
    """Interactive stdin confirmation (y/N)."""
    print(format_batch_preview(batch))
    answer = input("push this batch to wire? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def run_writeback_confirmed(
    conn: Any,
    namespace: str = "wire",
    client: Any = None,
    *,
    confirm: Optional[Callable[[list[dict]], bool]] = None,
    dry_run: bool = False,
    force: bool = False,
    limit: int = 1000,
) -> dict:
    """Operator-gated writeback run (task 1.2, design D3).

    - Preview the pending batch; require explicit confirmation BEFORE any
      network write (default: interactive stdin; inject ``confirm=lambda
      batch: True`` for scripted/``--yes`` use).
    - ``dry_run=True`` returns the preview WITHOUT any confirmation prompt or
      write — pure planning surface.
    - Unconfirmed → ``{"confirmed": False, "pushed": False}`` and zero writes.
    - Confirmed → kernel ``run_writeback`` (per-unit honest failure discipline
      unchanged; skipped-units idempotency unchanged; ``force`` re-sends).
    """
    promotion = _load_kernel()
    batch = pending_batch(conn, namespace, limit=limit)
    if dry_run:
        return {
            "confirmed": None,
            "pushed": False,
            "preview": format_batch_preview(batch),
            "batch": batch,
        }
    confirm_fn = confirm if confirm is not None else _default_confirm
    if not confirm_fn(batch):
        return {"confirmed": False, "pushed": False, "preview": format_batch_preview(batch)}
    result = promotion.run_writeback(conn, namespace, WireWriteback(client),
                                     force=force, limit=limit)
    return {"confirmed": True, "pushed": True, **result}


def run_writeback(conn: Any, namespace: str = "wire", client: Any = None) -> dict:
    """Direct kernel run (NO confirmation gate) — kept for tests/hermetic runs;
    live operators should use :func:`run_writeback_confirmed`."""
    promotion = _load_kernel()
    return promotion.run_writeback(conn, namespace, WireWriteback(client))


__all__ = [
    "BENCH_NOTE_KEY",
    "WireWriteback",
    "format_batch_preview",
    "format_bench_stamp",
    "pending_batch",
    "run_writeback",
    "run_writeback_confirmed",
]
