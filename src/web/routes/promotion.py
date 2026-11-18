"""Promotion queue routes over the bench kernel's promotion machine.

Views (any authenticated caller, like ``review.py``'s read pages) and
operations (scope-gated, like review's decide POST):

- ``GET  /promotion/queue``           paged queue + per (namespace,kind,tier) counts
- ``POST /promotion/units/.../annotate``   attach tags/attrs (scope ``review:annotate``)
- ``POST /promotion/units/.../promote``     step up the ladder (scope ``review:annotate``)
- ``POST /promotion/writeback``            push golds back to the registry (scope ``admin``)

The reviewer stamp on promote is ALWAYS the session identity (``_reviewer_of``
below) — the request body can never set it, following the same discipline as
``review.py``'s annotator stamp. Gold promotion refuses without it (kernel
guard), and the tier chain (bronze→silver→gold, one way) is enforced by
``src/bench/promotion.py``.

Writeback runs through the kernel ``run_writeback`` with a channel resolved
by :func:`_resolve_writeback_fn`. The public repo ships NO registry client
(the wire connector lives in the internal repo), so with no channel configured
every payload fails honestly — the unit is NOT marked written back and the
result list says why; operators run writeback via the internal connector or a
registered channel.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.deps import User, get_current_user, require_scope
from ..deps import DbConn, get_db
from ...bench import promotion
from ...bench.promotion import TierTransitionError, UnitNotFoundError

read_only_router = APIRouter(tags=["promotion"])
write_router = APIRouter(tags=["promotion"])

#: Human-verification ops ride the annotator bundle (same as review decide).
PROMOTE_SCOPE = "review:annotate"
#: Pushing gold back to the external registry is an admin op.
WRITEBACK_SCOPE = "admin"

#: Response fields allowed in a promote request body. ``reviewer`` is
#: deliberately NOT one of them — it comes from the session, never the form.
_PROMOTE_BODY_KEYS = {"namespace", "to_tier", "note", "sensitivity", "force"}


def _reviewer_of(user: User) -> str:
    """Stable, readable reviewer stamp from the session identity.

    Same construction as ``review.py::_annotator_of``: email first (what an
    operator recognises), then display name, then the opaque ``sub`` so a
    stamp always exists.
    """
    return user.email or user.name or user.sub


def _resolve_writeback_fn() -> Optional[Callable[[dict], Any]]:
    """Registry writeback channel hook.

    ``None`` means "no channel configured in this deployment" (the public
    kernel intentionally ships no wire client; the internal wire-connector
    registers one here or drives ``run_writeback`` directly). When unset, the
    writeback endpoint degrades honestly: each payload is attempted through a
    stub that raises, so units stay un-marked and the response lists the
    reason per unit.
    """
    return getattr(promotion_writeback_channel, "fn", None)


class promotion_writeback_channel:  # noqa: N801 - module-level hook holder
    """Deployment hook: set ``fn = callable`` to enable HTTP-triggered
    writeback (the internal connector does this at wiring time)."""

    fn: Optional[Callable[[dict], Any]] = None


def _stub_writeback(payload: dict) -> Any:
    raise RuntimeError(
        "no registry writeback channel configured in this deployment; "
        "run the internal wire-connector (writeback.py) or register "
        "promotion_writeback_channel.fn"
    )


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return body


# ------------------------------------------------------------------- views


@read_only_router.get("/promotion/queue")
def promotion_queue_view(
    namespace: str | None = None,
    kind: str | None = None,
    tier: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: DbConn = Depends(get_db),
) -> dict:
    """Paged promotion queue with per (namespace, kind, tier) counts.

    Read view: any authenticated caller may look (same posture as
    ``review.py``'s pages); only the promotion/writeback operations carry the
    scope gate.
    """
    if kind is not None and kind not in promotion.PROMOTABLE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {list(promotion.PROMOTABLE_KINDS)}",
        )
    if tier is not None and tier not in promotion.CHAIN:
        raise HTTPException(
            status_code=400, detail=f"tier must be one of {list(promotion.CHAIN)}"
        )
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    return promotion.promotion_queue(
        db, namespace=namespace, kind=kind, tier=tier, limit=limit, offset=offset
    )


# ------------------------------------------------------------------ operations


@write_router.post("/promotion/units/{kind}/{external_key}/annotate")
async def annotate(
    request: Request,
    kind: str,
    external_key: str,
    user: User = Depends(require_scope(PROMOTE_SCOPE)),
    db: DbConn = Depends(get_db),
) -> dict:
    """Attach operator tags/attrs (annotation step; does not move the tier)."""
    if kind not in promotion.PROMOTABLE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {list(promotion.PROMOTABLE_KINDS)}",
        )
    body = await _json_body(request)
    namespace = body.get("namespace")
    if not namespace:
        raise HTTPException(status_code=400, detail="namespace is required")
    tags = body.get("tags") or {}
    attrs = body.get("attrs") or {}
    if not isinstance(tags, dict) or not isinstance(attrs, dict):
        raise HTTPException(status_code=400, detail="tags/attrs must be objects")
    try:
        unit = promotion.annotate_unit(
            db,
            kind=kind,
            external_key=external_key,
            namespace=namespace,
            tags=tags,
            attrs=attrs,
            reviewer=_reviewer_of(user),
        )
    except UnitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return unit


@write_router.post("/promotion/units/{kind}/{external_key}/promote")
async def promote(
    request: Request,
    kind: str,
    external_key: str,
    user: User = Depends(require_scope(PROMOTE_SCOPE)),
    db: DbConn = Depends(get_db),
) -> dict:
    """Step a unit up the bronze→silver→gold ladder.

    Accepted body keys: ``namespace``, ``to_tier``, ``note``, ``sensitivity``,
    ``force``. The reviewer identity is taken from the session — a
    ``reviewer`` key in the body is rejected, never trusted.
    """
    if kind not in promotion.PROMOTABLE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {list(promotion.PROMOTABLE_KINDS)}",
        )
    body = await _json_body(request)
    unexpected = set(body) - _PROMOTE_BODY_KEYS
    if unexpected:
        raise HTTPException(
            status_code=400,
            detail=f"unexpected body keys {sorted(unexpected)}; "
                   "reviewer comes from the session, not the body",
        )
    namespace = body.get("namespace")
    to_tier = body.get("to_tier")
    if not namespace or not to_tier:
        raise HTTPException(status_code=400, detail="namespace and to_tier are required")
    try:
        unit = promotion.promote_unit(
            db,
            kind=kind,
            external_key=external_key,
            namespace=namespace,
            to_tier=to_tier,
            reviewer=_reviewer_of(user),
            note=str(body.get("note") or ""),
            sensitivity=body.get("sensitivity"),
            force=bool(body.get("force")),
        )
    except TierTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return unit


@write_router.post("/promotion/writeback")
async def writeback(
    request: Request,
    user: User = Depends(require_scope(WRITEBACK_SCOPE)),
    db: DbConn = Depends(get_db),
) -> dict:
    """Push every gold payload in a namespace back through the write channel.

    Kernel guarantees hold regardless of channel: success records the receipt
    and marks written_back; a raising channel leaves the unit un-marked,
    continues with the rest, and the returned counts state exactly what
    happened. Already-written units are skipped (registry key = idempotency
    key) unless ``force`` is set.
    """
    body = await _json_body(request)
    namespace = body.get("namespace")
    if not namespace:
        raise HTTPException(status_code=400, detail="namespace is required")
    fn = _resolve_writeback_fn() or _stub_writeback
    result = promotion.run_writeback(
        db, namespace, fn, force=bool(body.get("force"))
    )
    return result


router = APIRouter(tags=["promotion"])
router.include_router(read_only_router)
router.include_router(write_router)
