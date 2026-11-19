"""Knowledge-distribution web surface (change ``add-knowledge-distribution-contract``).

Two audiences live in this module:

1. **Machine pull API** — ``GET /api/v1/distribution/{domain_key}/ontology``
   serves versioned, immutable publication snapshots to registered consumers.
   It is deliberately Logto-free (spec: 拉取面 SHALL NOT 依赖 Logto 交互会话):
   the credential is the consumer's ``X-Consumer-Token`` header. Auth wiring
   (option (a) of the design's two options): the prefix
   ``/api/v1/distribution/`` is listed in ``_EXEMPT_PREFIXES``
   (``src/web/auth/deps.py``), so the app-level ``get_current_user`` resolves
   these paths to the anonymous sentinel — the same mechanism the invitation
   pages use — and THIS route performs its own token auth. The route never
   calls ``get_current_user`` / ``require_scope``. It is not mounted on
   ``public_app``.

   Three-state auth (spec ``knowledge-distribution`` 机器拉取面, exact):

   ==============  =====================================================
   missing header  401  ``缺少机器凭据：X-Consumer-Token 请求头``
   unknown token   403  ``令牌未登记``
   revoked token   403  ``令牌已吊销``        (distinct from unregistered)
   out-of-scope    403  ``该域不在绑定范围``  (domain content never leaked)
   no publication  404  ``该域尚无发布`` / ``该域无版本 v{N}``
   ==============  =====================================================

   The plaintext token is hashed on arrival and never logged or echoed; no
   error detail ever includes it.

   **Pull payload shape — the contract fd-wire codes against** (JSON,
   insertion order; the same tree is what ``format=yaml`` dumps):

   ::

       {
         "domain":              "<domain_key>",
         "template_name":       "<the domain's template name>",
         "template_version":    <manifest's template-version anchor>,
         "publication_version": <monotonic publication version N>,
         "digest":              "<sha256 of the canonical manifest>",
         "entities":            [ {kind, external_key, body, tier,
                                    sensitivity, attrs}, ... ],
         "relationships":       [ same item shape; attrs carries the
                                    structured "from"/"to" (+ from_key/
                                    to_key); external_key follows the
                                    authoring convention
                                    "{from_key}->{kind}:{to_key}" ],
         "changelog":           {diff vs the previous publication
                                    (added/removed/changed); the first
                                    version is {"initial": true, ...}}
       }

   ``entities``/``relationships`` are the frozen manifest's arrays verbatim
   (item fields per the kernel contract: kind/external_key/body/tier/
   sensitivity/attrs; ``sensitivity`` mirrors the KU's ``tags.sensitivity``,
   null when absent). ``?version=N`` pins a historical snapshot (byte-identical
   to its publish-time digest); default is the latest version. ``?format=json``
   (default) returns ``application/json``; ``?format=yaml`` returns
   ``application/x-yaml`` via ``yaml.safe_dump(..., allow_unicode=True,
   sort_keys=False)`` — PyYAML lives in the route layer only, the kernel stays
   dependency-free. Any other ``format`` is 422 naming the allowed values.

2. **Admin management** (Logto side): the consumer registry at
   ``/admin/distribution`` (``require_scope("admin")``) — register (issue
   token), revoke, rebind domains — and the per-domain publish action
   ``POST /admin/domains/{domain_key}/publish`` composed C1-style:
   ``require_scope("content:write")`` + ``require_domain_role("lead")``
   (admins bypass the domain check). The publications listing is rendered on
   the C1 domain detail page; its context is fetched in
   ``admin.py::admin_domain_detail`` (this module owns the publish POST).

3. **Machine run read-back** — ``GET /api/v1/distribution/{domain_key}/runs``
   (``add-fleet-execution-loop`` §3.5). Same credential and same three-state
   check as the pull API, but only a ``fleet`` registration may call it: a fleet
   writes back its round through the kernel and then needs to answer "did it
   land, and how did it end?" without a browser session. A plain ``machine``
   consumer (a publication reader) is refused with 403 rather than served an
   empty ledger, and a fleet only ever sees rounds under its own
   ``fleet:<fleet_ref>/`` prefix. The session twin is
   ``GET /api/d/{domain_key}/runs`` in ``console.py``; both share the predicate
   ``submitters.may_read_runner_ref``.

Token discipline follows the C1 invitation pattern: ``secrets.token_urlsafe(32)``,
only ``hashlib.sha256(token).hexdigest()`` persisted via
``distribution.register_consumer(token_hash=...)``, plaintext shown exactly
once — in the creation flash.

The data layer is ``src/bench/distribution.py`` (kernel); this module stays a
thin web surface with the ``admin.py`` flash/redirect style.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Optional
from urllib.parse import quote

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ..auth.deps import User, require_scope
from ..auth.domain_rbac import require_domain_role
from ..deps import DbConn, get_db
from ..templating import templates as _templates
from ...bench import distribution
from ...bench import workspaces

read_only_router = APIRouter(tags=["distribution"])
write_router = APIRouter(tags=["distribution"])


def _flash(
    path: str, msg: str, err: bool = False, status: int = 303, **interp
) -> RedirectResponse:
    """Redirect with a flash message — same contract as ``admin.py::_flash``.

    ``msg`` is a dotted i18n key resolved by ``base.html``'s ``tr`` helper;
    ``**interp`` values ride along as extra query params (the base template
    forwards ``name`` and ``detail`` into ``tr``).
    """
    sep = "&" if "?" in path else "?"
    q = f"msg={quote(msg)}"
    if err:
        q += "&err=1"
    for key, val in interp.items():
        q += f"&{key}={quote(str(val))}"
    return RedirectResponse(f"{path}{sep}{q}", status_code=status)


def _operator_of(user: User) -> str:
    """Stable, readable operator stamp — same construction as ``admin.py``."""
    return user.email or user.name or user.sub


def _split_domains(raw: Any) -> list[str]:
    """Parse the comma-separated domain-keys form field (deduped, order kept)."""
    seen: list[str] = []
    for part in str(raw or "").split(","):
        key = part.strip()
        if key and key not in seen:
            seen.append(key)
    return seen


# ------------------------------------------------------------ machine pull #
# Logto-free: this path prefix is exempted from the app-level get_current_user
# (see _EXEMPT_PREFIXES in src/web/auth/deps.py); the token check below IS the
# authentication for this surface.

_MISSING_TOKEN_DETAIL = "缺少机器凭据：X-Consumer-Token 请求头"
_UNREGISTERED_DETAIL = "令牌未登记"
_REVOKED_DETAIL = "令牌已吊销"
_OUT_OF_SCOPE_DETAIL = "该域不在绑定范围"
_NO_PUBLICATION_DETAIL = "该域尚无发布"

_ALLOWED_FORMATS = ("json", "yaml")


def _authenticate_consumer(request: Request, db: Any, domain_key: str) -> dict:
    """Three-state machine auth, shared by every ``/api/v1/distribution`` route.

    One implementation on purpose: the read-back route below answers "did my run
    land?" for the *same* credential that pulls content. A second copy of this
    check would drift, and the drift would look like a scope bug rather than a
    missing branch.
    """
    token = request.headers.get("x-consumer-token")
    if not token:
        raise HTTPException(status_code=401, detail=_MISSING_TOKEN_DETAIL)
    # Hash immediately; the plaintext never reaches a log, DB row, or error.
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    consumer = distribution.get_consumer_by_token_hash(db, token_hash=token_hash)
    if consumer is None:
        raise HTTPException(status_code=403, detail=_UNREGISTERED_DETAIL)
    if consumer.get("revoked_at") is not None:
        raise HTTPException(status_code=403, detail=_REVOKED_DETAIL)
    if domain_key not in (consumer.get("domains") or []):
        raise HTTPException(status_code=403, detail=_OUT_OF_SCOPE_DETAIL)
    return consumer


@read_only_router.get("/api/v1/distribution/{domain_key}/ontology", name="distribution_pull_ontology")
def pull_domain_ontology(
    domain_key: str,
    request: Request,
    version: Optional[int] = None,
    format: str = "json",
    db: DbConn = Depends(get_db),
):
    """Serve one publication snapshot to a registered consumer (see module docstring).

    Auth is the spec's three-state token check — no Logto identity involved.
    ``version=None`` fetches the latest publication; ``format`` is ``json``
    (default) or ``yaml``. The payload shape is documented in the module
    docstring — fd-wire codes against it.
    """
    fmt = (format or "").strip().lower()
    if fmt not in _ALLOWED_FORMATS:
        raise HTTPException(
            status_code=422,
            detail="invalid format: allowed values are 'json' or 'yaml'",
        )

    consumer = _authenticate_consumer(request, db, domain_key)

    publication = distribution.get_publication(db, domain_key=domain_key, version=version)
    if publication is None:
        detail = _NO_PUBLICATION_DETAIL if version is None else f"该域无版本 v{version}"
        raise HTTPException(status_code=404, detail=detail)

    manifest = publication.get("manifest") or {}
    domain_row = workspaces.get_domain(db, domain_key=domain_key)

    # C5 pull footprint: record the successful pull (append-only; the consumer
    # row itself is never updated). Only a pull that actually resolved a
    # publication reaches this line — a rejected credential or a 404 above
    # never does, so the trail never claims a pull that did not happen.
    # Best effort: a footprint write must never turn a served snapshot into a
    # 500, so a failure here is swallowed by design (the payload is already
    # computed and remains correct).
    try:
        db.execute(
            "INSERT INTO distribution_pull_events (consumer_id, domain_key, version) "
            "VALUES (%s, %s, %s)",
            (consumer["id"], domain_key, publication["version"]),
        )
        db.commit()
    except Exception:  # noqa: BLE001 - see the comment above
        pass

    payload = {
        "domain": manifest.get("domain") or domain_key,
        "template_name": manifest.get("template_name")
        or (domain_row or {}).get("template_name"),
        "template_version": manifest.get("template_version"),
        "publication_version": publication["version"],
        "digest": publication["digest"],
        "entities": manifest.get("entities") or [],
        "relationships": manifest.get("relationships") or [],
        "changelog": publication.get("changelog"),
    }
    if fmt == "yaml":
        body = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        return Response(content=body, media_type="application/x-yaml")
    return JSONResponse(content=payload)


@read_only_router.get(
    "/api/v1/distribution/{domain_key}/runs", name="distribution_run_readback",
)
def read_back_runs(
    domain_key: str,
    request: Request,
    runner_ref: Optional[str] = None,
    limit: int = 50,
    db: DbConn = Depends(get_db),
):
    """Read back the fleet's own run rows — "did my write-back land?".

    Same credential as the pull API (``X-Consumer-Token``), same three-state
    check. Only a ``fleet`` registration may ask: a plain ``machine`` consumer is
    a reader of publications, not a submitter, and 403 is the honest answer
    rather than an empty ledger.

    Isolation: a fleet sees only ``fleet:<its own fleet_ref>/`` rounds, and the
    response always says which fleet answered and which rows matched — so a fleet
    that wrote back under a slightly different ``fleet_ref`` sees "0 rows" *next
    to its own identity*, not an ambiguous empty list.
    """
    from ...bench import agent_runs, submitters

    consumer = _authenticate_consumer(request, db, domain_key)
    fleet_ref = consumer.get("fleet_ref")
    if (consumer.get("kind") or "machine") != "fleet" or not fleet_ref:
        raise HTTPException(
            status_code=403,
            detail="只有舰队登记可以读取运行回执（该消费者不是 fleet 种类）",
        )

    wanted = (runner_ref or "").strip() or None
    if wanted is not None and not submitters.may_read_runner_ref(wanted, fleet_ref=fleet_ref):
        raise HTTPException(
            status_code=403,
            detail=f"只能读取本舰队的运行：runner_ref={wanted!r} 不属于 {fleet_ref}",
        )

    rows = agent_runs.list_runs(
        db, domain_key=domain_key, runner_ref=wanted, limit=limit
    )
    # 未指定 runner_ref 时只返回本舰队的行：一个舰队读面没有理由把它们全公布。
    rows = [r for r in rows if submitters.may_read_runner_ref(
        r.get("runner_ref"), fleet_ref=fleet_ref
    )]
    return {
        "domain": domain_key,
        "fleet_ref": fleet_ref,
        "runner_ref": wanted,
        "count": len(rows),
        "runs": rows,
    }


#: Closed vocabularies the verdict read face accepts. Kept next to the routes
#: rather than imported from ``src.bench.verdicts`` so a bad value is refused
#: BEFORE any DB work, and so the import stays lazy like the rest of this module.
VERDICT_GATES = ("no-worse", "regression", "all-pass", "calibrated")
VERDICT_OUTCOMES = ("pass", "fail", "inconclusive")


def _reject_unknown(value, allowed, field: str) -> None:
    """A wrong enum is a caller bug, not a filter that matches nothing."""
    if value in (None, ""):
        return
    if value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{field} '{value}' 不在闭集内：{list(allowed)}",
        )


def _fleet_consumer(request: Request, db: Any, domain_key: str) -> dict:
    """Authenticate AND require a ``fleet`` registration, returning it.

    Every mutating machine route needs the same two steps; a second copy would
    drift and the drift would read as a scope bug rather than a missing branch.
    """
    consumer = _authenticate_consumer(request, db, domain_key)
    if (consumer.get("kind") or "machine") != "fleet" or not consumer.get("fleet_ref"):
        raise HTTPException(
            status_code=403,
            detail="只有舰队登记可以调用该接口（该消费者不是 fleet 种类）",
        )
    return consumer


def _fleet_task(db: Any, *, domain_key: str, task_id: int, fleet_ref: str) -> dict:
    """The task, if it is genuinely assigned to this fleet in this domain.

    Authorization reads ``assignee_kind`` + ``assignee_ref``, never the display
    name: a fleet called "ontology-fleet" and another one displaying the same
    string are two different identities, and only the registered ref decides.
    """
    from ...bench import authoring, workspaces

    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"域 {domain_key!r} 不存在")
    task = authoring.authoring_get_task(db, task_id=task_id)
    if task is None or task["domain_id"] != domain["id"]:
        raise HTTPException(status_code=404, detail=f"工单 {task_id} 不在本域")
    if task.get("assignee_kind") != "fleet" or task.get("assignee_ref") != fleet_ref:
        raise HTTPException(
            status_code=403,
            detail=(
                f"该工单不是派给舰队 {fleet_ref!r} 的"
                f"（现在是 {task.get('assignee_kind')}/{task.get('assignee_ref')!r}）"
            ),
        )
    return task


@read_only_router.get(
    "/api/v1/distribution/{domain_key}/work-orders",
    name="distribution_list_work_orders",
)
def list_work_orders(
    domain_key: str,
    request: Request,
    db: DbConn = Depends(get_db),
):
    """The fleet's own **open** work orders in this domain.

    A fleet cannot claim work it cannot see: the console page is for people, and
    the ledger page answers "what ran", not "what is waiting for me". So the
    pull side exists — and it is strictly the caller's own orders:

    - only ``pending`` / ``in_progress`` (a closed order is not work to claim),
    - only ``assignee_kind='fleet'`` with ``assignee_ref == this fleet``,
    - only this domain (the token's binding already gated the path).

    Reading has no side effects at all — no status change, no event, no
    pull-footprint row: the ontology pull writes a footprint because "who fetched
    which snapshot" is an audit question; "a fleet polled its queue" is not.
    """
    from ...bench import authoring, workspaces

    consumer = _fleet_consumer(request, db, domain_key)
    fleet_ref = consumer["fleet_ref"]
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"域 {domain_key!r} 不存在")

    tasks = [
        t
        for t in authoring.authoring_list_tasks(db, domain_id=domain["id"])
        if t["status"] in ("pending", "in_progress")
        and t.get("assignee_kind") == "fleet"
        and t.get("assignee_ref") == fleet_ref
    ]
    return {
        "domain": domain_key,
        "fleet_ref": fleet_ref,
        "count": len(tasks),
        "work_orders": [
            {
                "id": t["id"],
                "target_kind": t.get("target_kind"),
                "target_key": t.get("target_key"),
                "title": t["title"],
                "detail": t.get("detail"),
                "status": t["status"],
                "created_at": t.get("created_at"),
                # 认领过就把「谁、什么时候」一起给出去：执行方要能分清
                # 「这张单还没人动」与「我自己上一轮已经领了」。
                "claimed_by": next(
                    (
                        e.get("by")
                        for e in reversed(t.get("transitions") or [])
                        if e.get("to") == "in_progress"
                    ),
                    None,
                ),
            }
            for t in tasks
        ],
    }


@write_router.post(
    "/api/v1/distribution/{domain_key}/work-orders/{task_id}/claim",
    name="distribution_claim_work_order",
)
def claim_work_order(
    domain_key: str,
    task_id: int,
    request: Request,
    db: DbConn = Depends(get_db),
):
    """A fleet claims the work order addressed to it.

    Why a machine route exists at all: the session route treats a non-human
    assignee as "not mine", so only a lead could move it — and a lead clicking
    "in progress" on a fleet's behalf is not the fleet claiming. Without this the
    wording "waiting for a fleet to claim it" would describe something that can
    never happen, which is exactly the kind of closed-looking loop this change
    exists to remove.

    Exclusive by construction: the kernel's claim is one ``UPDATE ... WHERE
    status='pending'``, so two fleets racing produce one winner and one 409.

    **Own retries are idempotent.** A machine endpoint gets retried by the
    network, not by a human who remembers clicking. "Already claimed — by me" is
    a success (``created: false``); only *another* fleet's claim is a conflict.
    Answering 409 to our own retry would make a healthy fleet log a failure it
    cannot fix by retrying again.
    """
    from ...bench import authoring

    consumer = _fleet_consumer(request, db, domain_key)
    existing = _fleet_task(db, domain_key=domain_key, task_id=task_id,
                           fleet_ref=consumer["fleet_ref"])
    actor = consumer.get("fleet_ref")
    if existing["status"] == "in_progress":
        claimed_by = next(
            (e.get("by") for e in reversed(existing.get("transitions") or [])
             if e.get("to") == "in_progress"),
            None,
        )
        if claimed_by == actor:
            return {"task": existing, "claimed_by": actor, "created": False}
        raise HTTPException(
            status_code=409,
            detail=f"工单 {task_id} 已被 {claimed_by!r} 认领",
        )
    try:
        task = authoring.authoring_claim_task(db, task_id=task_id, actor=actor)
    except authoring.TaskAlreadyClaimed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"task": task, "claimed_by": actor, "created": True}


@write_router.post(
    "/api/v1/distribution/{domain_key}/work-orders/{task_id}/complete",
    name="distribution_complete_work_order",
)
async def complete_work_order(
    domain_key: str,
    task_id: int,
    request: Request,
    db: DbConn = Depends(get_db),
):
    """A fleet closes the work order it claimed (artifact refs + note optional).

    Completing writes **no** knowledge unit: a work order says "this got done".
    Content still arrives through the proposal inbox, so "task done" can never
    quietly become "knowledge published".

    Idempotent on retry: an already-`done` order returns ``created: false``
    instead of a conflict. The desired end state holds, so a retried request is a
    success — a fresh `done` event is never appended twice.
    """
    from ...bench import authoring

    consumer = _fleet_consumer(request, db, domain_key)
    current = _fleet_task(db, domain_key=domain_key, task_id=task_id,
                          fleet_ref=consumer["fleet_ref"])
    if current["status"] == "done":
        return {"task": current, "created": False}
    body: dict = {}
    # 空体合法（关单可以什么都不说）；**写坏的 JSON 不合法**——把它当空体处理，
    # 舰队会以为 note 记上了，而台账里一个字都没有。这两种情况必须分开。
    raw = await request.body()
    if raw.strip():
        try:
            payload = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
        body = payload

    refs = body.get("artifact_refs")
    if refs is not None and not isinstance(refs, list):
        raise HTTPException(status_code=422, detail="artifact_refs 必须是数组")
    try:
        task = authoring.authoring_complete_task(
            db, task_id=task_id, actor=consumer["fleet_ref"],
            artifact_refs=refs, note=(body.get("note") or None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"task": task, "created": True}


@write_router.post(
    "/api/v1/distribution/{domain_key}/runs", name="distribution_record_run",
)
async def record_run(
    domain_key: str,
    request: Request,
    db: DbConn = Depends(get_db),
):
    """A fleet writes back one round's outcome — idempotent on ``runner_ref``.

    The kernel refuses to invent fields here: an outcome outside the four-state
    vocabulary is 422, a ``runner_ref`` belonging to another fleet is 403, and a
    replay returns ``created: false`` with the existing row unchanged. Without
    that flag a fleet cannot tell "recorded" from "already recorded", and its
    per-round counts become untrustworthy.
    """
    from ...bench import agent_runs, submitters

    consumer = _fleet_consumer(request, db, domain_key)
    fleet_ref = consumer["fleet_ref"]
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")

    runner_ref = str(payload.get("runner_ref") or "").strip()
    if not submitters.may_read_runner_ref(runner_ref, fleet_ref=fleet_ref):
        raise HTTPException(
            status_code=403,
            detail=f"runner_ref 必须形如 fleet:{fleet_ref}/<post>#<round>；got {runner_ref!r}",
        )
    role = str(payload.get("role") or "").strip()
    if not role:
        # 台账的第一列是岗位。允许空岗位，这条「谁在跑」的回答就永久缺一角。
        raise HTTPException(status_code=422, detail="role 不能为空（台账要回答是哪个岗位跑的）")
    task_id = payload.get("task_id")
    if task_id is not None:
        # 引用的工单必须在本域：跨域 task_id 会让「这轮做的是哪张单」指到别人家。
        # 非整数先拒成 422——让它冒到 int() 里就变成 500，那读起来像我们的故障。
        try:
            task_id = int(task_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="task_id 必须是整数") from exc
        _fleet_task(db, domain_key=domain_key, task_id=task_id, fleet_ref=fleet_ref)
    counts = payload.get("counts")
    refs = payload.get("artifact_refs")
    for name, value, kind in (
        ("counts", counts, dict), ("artifact_refs", refs, list),
    ):
        if value is not None and not isinstance(value, kind):
            raise HTTPException(
                status_code=422, detail=f"{name} 必须是 {kind.__name__}"
            )
    try:
        run, created = agent_runs.record_external_run(
            db,
            runner_ref=runner_ref,
            role=role,
            domain_key=domain_key,
            outcome=str(payload.get("outcome") or ""),
            counts=counts,
            remaining=payload.get("remaining"),
            artifact_refs=refs,
            detail=(payload.get("detail") or None),
            task_id=(int(task_id) if task_id is not None else None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run": run, "created": created}


@write_router.post(
    "/api/v1/distribution/{domain_key}/proposals", name="distribution_submit_proposal",
)
async def submit_proposal(
    domain_key: str,
    request: Request,
    db: DbConn = Depends(get_db),
):
    """A fleet submits a product **as itself**, with the token it already holds.

    Why this exists: the three machine routes above let a fleet claim, run and
    report — but the product of that work (the proposal) could only be filed
    through the session face, which requires a credential that represents a
    *person*. D7 rejected exactly that ("服务账号会话" would erase the
    human/machine boundary), yet the loop as first built still needed it: a
    token-only fleet could do the work and never hand it in. That is not a
    closed loop; it is a loop whose last step silently requires a human.

    The source is **not** free-form here. It must be ``fleet:<自己的 fleet_ref>/…``
    — the same prefix rule that governs run write-backs — so a token can only
    ever speak for its own registration. ``submitted_by`` is derived from that
    source, never taken from the body: a machine has one identity.

    ``via`` is the external channel, so ``extract:`` stays refused (its trust
    basis is that the pipeline is unreachable from the network), and
    ``authenticated_as`` is None, so ``agent:``/``user:`` can never be claimed
    by a token. Idempotency and the self-confirm gate are the library's.
    """
    from ...bench import proposals as bench_proposals
    from ...bench import submitters as bench_submitters

    consumer = _fleet_consumer(request, db, domain_key)
    fleet_ref = consumer["fleet_ref"]
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")

    source = str(payload.get("source") or "").strip()
    if not bench_submitters.may_submit_as_source(source, fleet_ref=fleet_ref):
        raise HTTPException(
            status_code=403,
            detail=f"source 必须形如 fleet:{fleet_ref}/<post>；got {source!r}"
                   "（机器面只能以自己的身份提交）",
        )
    try:
        proposal, created = bench_proposals.submit(
            db,
            domain_key=domain_key,
            source=source,
            kind=str(payload.get("kind") or "").strip(),
            external_key=str(payload.get("external_key") or "").strip(),
            body=str(payload.get("body") or "").strip(),
            evidence=payload.get("evidence"),
            impact=str(payload.get("impact") or ""),
            submitted_by=source,
            with_created=True,
            via=bench_submitters.VIA_HTTP,
            authenticated_as=None,
        )
    except bench_proposals.SubmitterRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except bench_proposals.ProposalTargetExists as exc:
        # 409，不是 422：请求本身没写错，是目标状态与它冲突（键已在本体 /
        # 端点未入库）。分档有实际后果——422 让调用方去改请求，409 让它去改
        # 既有单位或先补端点。`reason` 是稳定的机器词，客户端按它分支。
        raise HTTPException(
            status_code=409,
            detail={"reason": exc.reason, "message": exc.detail, "hint": exc.hint},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "id": proposal["id"],
        "state": proposal["state"],
        "external_key": proposal["external_key"],
        "evidence_digest": proposal["evidence_digest"],
        "created": created,
    }


@read_only_router.get(
    "/api/v1/distribution/{domain_key}/proposals/outcomes",
    name="distribution_proposal_outcomes",
)
def proposal_outcomes(
    domain_key: str,
    request: Request,
    source: str,
    db: DbConn = Depends(get_db),
):
    """What happened to the proposals this fleet filed — **only its own**.

    The other half of the same gap: a fleet told "rejected" on resubmission can
    never learn *why*, so it fixes the wrong thing or stops trying. The
    ``source`` is checked against the caller's registration rather than trusted
    because it was passed in — asking for another fleet's source is 403, not an
    empty list (an empty list reads as "nothing happened", which is a different
    and false statement).
    """
    from ...bench import proposals as bench_proposals
    from ...bench import submitters as bench_submitters

    consumer = _fleet_consumer(request, db, domain_key)
    fleet_ref = consumer["fleet_ref"]
    wanted = (source or "").strip()
    if not bench_submitters.may_submit_as_source(wanted, fleet_ref=fleet_ref):
        raise HTTPException(
            status_code=403,
            detail=f"只能读取自己来源的结局：{wanted!r} 不属于 fleet:{fleet_ref}/",
        )
    return {
        "domain": domain_key,
        "source": wanted,
        "outcomes": bench_proposals.list_outcomes(db, source=wanted, domain_key=domain_key),
    }


# --------------------------------------------------------- consumer registry #
# Platform-admin exclusive: consumers are the machine counterpart of invited
# members — admission, binding and revocation are all admin-scope operations.


@read_only_router.get(
    "/admin/distribution", include_in_schema=False, name="admin_distribution",
    dependencies=[Depends(require_scope("admin"))],
)
def admin_distribution(request: Request, db: DbConn = Depends(get_db)):
    """Consumer registry: binding, status, token issue/revoke/rebind forms."""
    return _templates.TemplateResponse(
        request,
        "admin_distribution.html",
        {"consumers": distribution.list_consumers(db)},
    )


@write_router.post(
    "/admin/distribution/consumers", include_in_schema=False,
    name="admin_consumer_register",
    dependencies=[Depends(require_scope("admin"))],
)
async def admin_consumer_register(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Register a consumer and mint its machine token — plaintext shown once.

    Only ``sha256(token)`` is persisted (``register_consumer(token_hash=...)``);
    the plaintext rides the creation flash, the single time it exists.
    """
    form = await request.form()
    name = (form.get("name") or "").strip()
    domains = _split_domains(form.get("domains"))
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        distribution.register_consumer(
            db, name=name, domains=domains, token_hash=token_hash,
            created_by=_operator_of(user),
        )
    except ValueError as exc:
        return _flash(
            "/admin/distribution", "flash.consumer_register_failed",
            err=True, detail=str(exc),
        )
    return _flash("/admin/distribution", "flash.consumer_registered", name=name, detail=token)


@write_router.post(
    "/admin/distribution/consumers/{name}/revoke", include_in_schema=False,
    name="admin_consumer_revoke",
    dependencies=[Depends(require_scope("admin"))],
)
async def admin_consumer_revoke(
    request: Request,
    name: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Revoke a consumer's token — pulls fail immediately (spec scenario)."""
    try:
        distribution.revoke_consumer(db, name=name)
    except ValueError as exc:
        return _flash("/admin/distribution", "flash.consumer_revoke_failed", err=True, detail=str(exc))
    return _flash("/admin/distribution", "flash.consumer_revoked", name=name)


@write_router.post(
    "/admin/distribution/consumers/{name}/domains", include_in_schema=False,
    name="admin_consumer_domains",
    dependencies=[Depends(require_scope("admin"))],
)
async def admin_consumer_domains(
    request: Request,
    name: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Replace a consumer's bound-domain set (binding change = whole-set swap)."""
    form = await request.form()
    domains = _split_domains(form.get("domains"))
    try:
        distribution.set_consumer_domains(db, name=name, domains=domains)
    except ValueError as exc:
        return _flash("/admin/distribution", "flash.consumer_domains_failed", err=True, detail=str(exc))
    return _flash(
        "/admin/distribution", "flash.consumer_domains_set",
        name=name, detail=", ".join(domains),
    )


# ----------------------------------------------------------------- publish #
# C1's two-gate composition: platform scope (content:write) then domain role
# (lead; admins bypass). The kernel enforces the data-side rules (unknown
# domain, empty domain) as ValueError; the route maps them to a failure flash.


@write_router.post(
    "/admin/domains/{domain_key}/publish", include_in_schema=False,
    name="admin_domain_publish",
    dependencies=[
        Depends(require_scope("content:write")),
        Depends(require_domain_role("lead")),
    ],
)
async def admin_domain_publish(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Freeze the domain's content into an immutable publication snapshot.

    Idempotency: ``publish_domain`` returns the existing row when the computed
    digest already exists for the domain — the flash distinguishes that case
    (no new snapshot) from a genuinely new version by checking the digests
    known before the call.
    """
    back = f"/admin/domains/{quote(domain_key)}"
    try:
        known = {
            p.get("digest")
            for p in distribution.list_publications(db, domain_key=domain_key)
        }
        publication = distribution.publish_domain(
            db, domain_key=domain_key, published_by=_operator_of(user)
        )
    except ValueError as exc:
        return _flash(back, "flash.publish_failed", err=True, detail=str(exc))
    if publication.get("digest") in known:
        return _flash(
            back, "flash.published_idempotent", detail=f"v{publication['version']}"
        )
    return _flash(
        back, "flash.published",
        detail=f"v{publication['version']} · digest {str(publication.get('digest'))[:12]}",
    )


router = APIRouter(tags=["distribution"])
router.include_router(read_only_router)
router.include_router(write_router)


# --------------------------------------------------- verdict ledger read face #
# add-eval-verdict-ledger exposed the ledger to in-process callers; a fleet that
# runs in another process (or another product line entirely) had no way to read
# it. These two routes are that way, and they are READ-ONLY by construction: no
# route here creates a verdict, and none triggers an evaluation — evaluations
# cost a judge lane and sometimes human gold.


@read_only_router.get(
    "/api/v1/distribution/{domain_key}/verdicts",
    name="distribution_verdict_list",
)
def list_domain_verdicts(
    domain_key: str,
    request: Request,
    subject_kind: Optional[str] = None,
    subject_key: Optional[str] = None,
    gate: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 100,
    db: DbConn = Depends(get_db),
):
    """The evaluation verdicts attributed to this domain, newest first.

    Scope is the same one the domain's run list uses (``rubric_domain_id`` +
    the ancestor chain), so a consumer that reads both can never see them
    disagree about what belongs here.

    Closed vocabularies are enforced on the way IN rather than filtered out on
    the way back: an unknown gate is a caller bug, and answering 200 with an
    empty list would look exactly like "no such verdicts" — a different and
    false statement.

    ``inconclusive`` rows are returned alongside the rest, never folded into
    ``fail``. A reader that collapses them learns the wrong lesson from a
    broken judge.
    """
    from ...bench import inheritance

    from ...eval import store as verdict_store

    _fleet_consumer(request, db, domain_key)
    _reject_unknown(gate, VERDICT_GATES, "gate")
    _reject_unknown(outcome, VERDICT_OUTCOMES, "outcome")

    domain = db.execute(
        "SELECT path FROM domains WHERE key = %s", (domain_key,)
    ).fetchone()
    if domain is None:
        raise HTTPException(status_code=404, detail=f"域不存在：{domain_key}")

    rows = verdict_store.list_verdicts(
        subject_kind=subject_kind,
        subject_key=subject_key,
        limit=max(1, min(int(limit or 100), 500)),
        db_path=db,
        domain_paths=inheritance.ancestors(domain["path"]),
    )
    if gate:
        rows = [r for r in rows if r.get("gate") == gate]
    if outcome:
        rows = [r for r in rows if r.get("outcome") == outcome]
    return {"domain": domain_key, "count": len(rows), "verdicts": rows}


@read_only_router.get(
    "/api/v1/distribution/{domain_key}/verdicts/{run_id}",
    name="distribution_verdict_get",
)
def get_domain_verdict(
    domain_key: str,
    run_id: int,
    request: Request,
    db: DbConn = Depends(get_db),
):
    """One verdict with its per-criterion evidence.

    The run is looked up first and its domain checked afterwards, so an id that
    belongs to another domain answers 404 rather than 403 — the distinction
    matters: 403 would confirm the id exists somewhere.
    """
    from ...bench import inheritance
    from ...eval import store as verdict_store

    _fleet_consumer(request, db, domain_key)
    domain = db.execute(
        "SELECT path FROM domains WHERE key = %s", (domain_key,)
    ).fetchone()
    if domain is None:
        raise HTTPException(status_code=404, detail=f"域不存在：{domain_key}")

    try:
        run = verdict_store.get_run(run_id, db_path=db)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"结论不存在：{run_id}") from None

    chain = set(inheritance.ancestors(domain["path"]))
    attributed = db.execute(
        "SELECT d.path FROM domains d "
        "JOIN eval_runs e ON e.rubric_domain_id = d.id WHERE e.id = %s",
        (run_id,),
    ).fetchone()
    if attributed is None or attributed["path"] not in chain:
        raise HTTPException(status_code=404, detail=f"结论不存在：{run_id}")
    return {"domain": domain_key, "verdict": run}


@read_only_router.get(
    "/api/v1/distribution/{domain_key}/rulers",
    name="distribution_ruler_list",
)
def list_domain_rulers(domain_key: str, request: Request, db: DbConn = Depends(get_db)):
    """The rulers this domain can be judged by, with their canonical digests.

    A consumer that self-evaluates has to name a digest; handing it the list of
    legal ones is what keeps it from inventing one. Rubric digests come from the
    SAME canonical-digest kernel ``verdicts.rubric_ruler`` uses at write time,
    so a verdict written here and a rule read here cannot disagree about "the
    same ruler".

    A rubric whose criteria cannot be read contributes nothing rather than
    failing the whole list: one broken row must not blank the surface.
    """
    from ...bench import domain_rubrics, verdicts as bench_verdicts

    _fleet_consumer(request, db, domain_key)
    domain = db.execute(
        "SELECT path FROM domains WHERE key = %s", (domain_key,)
    ).fetchone()
    if domain is None:
        raise HTTPException(status_code=404, detail=f"域不存在：{domain_key}")

    rulers: list[dict] = []
    for rubric in domain_rubrics.effective_rubrics(db, domain_path=domain["path"]):
        try:
            ruler = bench_verdicts.rubric_ruler(rubric["name"], db_path=db)
        except (KeyError, ValueError):
            continue
        rulers.append(ruler)
    return {"domain": domain_key, "count": len(rulers), "rulers": rulers}


@read_only_router.get(
    "/api/v1/distribution/{domain_key}/crosswalks",
    name="distribution_crosswalks",
)
def list_domain_crosswalks(
    domain_key: str,
    request: Request,
    entity: Optional[str] = None,
    db: DbConn = Depends(get_db),
):
    """Mapping assertions + their connectivity, for a **machine** consumer.

    Why this route exists at all: the three-state connector evidence is allowed
    to live on the platform (crosswalk KUs), and the ERP line's generator reads
    it from here instead of from its own file. Until this route existed that
    "platform is the read authority" sentence had no machine path — the session
    route below is Logto-gated, and the public pod serves a different audience.

    Deliberately the SAME rows the console read face serves, built by the same
    function: a second copy of the query would drift, and the drift would look
    like "the console shows one thing, the machine another" rather than like a
    bug. Strictly read-only — no footprint row, no ``last_used_at`` touch.

    The token's domain binding gates the path before any row is read; an
    out-of-scope domain answers 403 and never leaks whether the domain exists.
    """
    from ...bench import crosswalk, quality

    _authenticate_consumer(request, db, domain_key)
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"域不存在：{domain_key}")
    path = domain.get("path") or domain["key"]
    rows = crosswalk.list_rows(db, namespace=path, entity_key=entity)
    return {
        "domain": domain_key,
        "entity": entity,
        "count": len(rows),
        "crosswalks": rows,
        "gaps": quality.crosswalk_gaps(db, namespace=path),
    }
