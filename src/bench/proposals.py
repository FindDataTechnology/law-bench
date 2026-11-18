"""Domain proposal inbox: submission snapshots with an explicit review trail.

A proposal is a *snapshot plus workflow state*, never a second ontology store.
Its row holds what was submitted (kind, external key, body, evidence, impact)
so reviewers see exactly the material that was proposed even if the outside
world changes; the row never participates in retrieval and is never read by
the kernel. Confirmation is the only moment content enters the ontology, and
it does so through the one kernel path (``src.bench.authoring``), which gates
the kind against the domain's anchored template vocabulary and appends the
append-only ``authoring_events`` row. This module deliberately contains no
``INSERT INTO knowledge_units``: a proposal layer with its own write path
would silently fork the ontology and break provenance, so the kernel stays the
single content truth.

Three rules make the workflow auditable rather than best-effort:

- *Evidence is mandatory and digested.* A submission carries machine-readable
  evidence (a citation, a diff, a source record). Its canonical-JSON sha256
  is stored alongside so equality of evidence is decidable without trusting
  the submitter's formatting — resubmission after rejection is accepted only
  with genuinely new evidence.
- *Submission is idempotent per key.* The partial unique index on pending
  ``(domain, source, external_key)`` rows means one open proposal per upstream
  item; resubmitting the same key returns the existing row unchanged instead
  of accumulating an ever-growing inbox.
- *Approval is separated from submission.* A submitter cannot confirm their
  own proposal (admins may override explicitly), and every state transition
  appends a row to ``domain_proposal_events`` — an append-only trail with no
  UPDATE/DELETE code path, so the workflow history stays replayable.

Domain isolation is enforced at every entry point the same way authoring does
it: resolve the domain first (unknown key is refused), then scope every query
and write by its id, so one domain's inbox can never be read or decided
through another domain's key.

Style: borrowed connection (never opened or closed here), ``%s`` placeholders,
one ``conn.commit()`` at the end of each successful write, JSONB via
``json.dumps``/``json.loads``. Rows are decoded from either dict-row or plain
tuple cursors.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Optional

from fd_ontology_kernel import proposals as kernel_proposals
from fd_ontology_kernel.errors import ProposalStaleEvidence

from . import agent_ids, authoring, distribution, keys, submitters, templates, workspaces

# Mirror of the CHECK constraint on domain_proposals.state (see
# src/bench/workspace_store.py).
PROPOSAL_STATES = ("pending", "confirmed", "rejected")

#: Enforcement modes for the submitter check. ``strict`` refuses anything but
#: ``ok``; ``lenient`` records the verdict and lets the row in — it exists only
#: for the migration window and MUST NOT be a default.
MODE_STRICT = "strict"
MODE_LENIENT = "lenient"
_SUBMITTER_MODE_ENV = "BENCH_SUBMITTER_MODE"

#: Verdicts lenient mode still refuses. Impersonating the in-process extraction
#: pipeline is forgery, not a legacy artefact: a migration window is not a
#: licence to pretend to be another writer.
_NEVER_TOLERATED = ("pipeline_impersonation",)

#: One message per verdict so the caller is told what to fix rather than
#: "forbidden". Keys mirror ``submitters.VERDICTS``.
_VERDICT_MESSAGES = {
    "unregistered": "来源未登记",
    "revoked": "来源登记已吊销",
    "domain_mismatch": "域不在绑定范围",
    "pipeline_impersonation": "该类来源仅限进程内调用",
    "agent_domain_mismatch": "身份与域不一致",
    "agent_not_member": "身份不是该域活跃成员",
    "user_mismatch": "只能以自己的身份提交",
    "malformed": "来源形状不合法（" + "；".join(submitters.SHAPES.values()) + "）",
    "unknown_prefix": "未知来源类别（可用：" + "、".join(submitters.SHAPES) + "）",
}


class SubmitterRefused(ValueError):
    """The submission's source is not an acceptable submitter for this domain.

    Carries the machine-readable ``verdict`` so the HTTP layer maps it to 403
    with the right sentence instead of pattern-matching the message text.
    """

    def __init__(self, verdict: str, *, source: str, domain_key: str):
        self.verdict = verdict
        self.source = source
        self.domain_key = domain_key
        message = _VERDICT_MESSAGES.get(verdict) or f"来源不可接受（{verdict}）"
        super().__init__(f"{message}：source={source!r} domain={domain_key!r}")


def _submitter_mode() -> str:
    """Current enforcement mode, read per call.

    Read at call time rather than import time: a value snapshotted at import
    cannot be flipped without a restart, and the lenient window is supposed to
    end on a measured count, not on a deploy.
    """
    raw = (os.environ.get(_SUBMITTER_MODE_ENV) or MODE_STRICT).strip().lower()
    return MODE_LENIENT if raw == MODE_LENIENT else MODE_STRICT

_PROPOSAL_COLS = (
    "id, domain_id, source, sources, kind, external_key, body, evidence, "
    "evidence_digest, impact, state, submitted_by, submitted_at, "
    "decided_by, decided_at, decision_note"
)
_PROPOSAL_KEYS = (
    "id",
    "domain_id",
    "source",
    "kind",
    "external_key",
    "body",
    "evidence",
    "evidence_digest",
    "impact",
    "state",
    "submitted_by",
    "submitted_at",
    "decided_by",
    "decided_at",
    "decision_note",
)

_EVENT_COLS = "id, proposal_id, from_state, to_state, actor, note, happened_at"
_EVENT_KEYS = (
    "id",
    "proposal_id",
    "from_state",
    "to_state",
    "actor",
    "note",
    "happened_at",
)

# Marker prefixed to the decision note when an admin confirms over the
# self-confirm ban. Its presence is the audit signal that the normal
# separation of duties was deliberately waived.
_ADMIN_OVERRIDE_TAG = "[admin-override]"


# ------------------------------------------------------------------ decoding


def _iso(val: Any) -> Any:
    """Return a consistent ISO-8601 string for driver timestamps; pass text through."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _decode_jsonb(val: Any) -> Any:
    if isinstance(val, (dict, list)) or val is None:
        return val
    return json.loads(val)


def _scalar(row: Any) -> Any:
    """First value of a single-column row, dict-row or tuple."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _proposal_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _PROPOSAL_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "domain_id": values[1],
        "source": values[2],
        "kind": values[3],
        "external_key": values[4],
        "body": values[5],
        "evidence": _decode_jsonb(values[6]),
        "evidence_digest": values[7],
        "impact": values[8],
        "state": values[9],
        "submitted_by": values[10],
        "submitted_at": _iso(values[11]),
        "decided_by": values[12],
        "decided_at": _iso(values[13]),
        "decision_note": values[14],
    }


def _event_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _EVENT_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "proposal_id": values[1],
        "from_state": values[2],
        "to_state": values[3],
        "actor": values[4],
        "note": values[5],
        "happened_at": _iso(values[6]),
    }


# ------------------------------------------------------------------- helpers


def _load_domain(conn: Any, *, domain_key: str) -> dict:
    """Resolve the domain or refuse the operation (fail-closed isolation)."""
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"domain {domain_key!r} not found")
    return domain


def _load_proposal(conn: Any, *, domain_id: int, proposal_id: int) -> Optional[dict]:
    """Fetch one proposal scoped to its domain; ``None`` when out of scope.

    The domain id is part of the predicate on purpose: a row that exists in
    another domain is indistinguishable from a missing row here, so a wrong
    domain key can never leak (or decide) foreign content.
    """
    row = conn.execute(
        f"SELECT {_PROPOSAL_COLS} FROM domain_proposals "
        "WHERE id = %s AND domain_id = %s",
        (proposal_id, domain_id),
    ).fetchone()
    return _proposal_to_dict(row) if row else None


def _record_event(
    conn: Any,
    *,
    proposal_id: int,
    from_state: Optional[str],
    to_state: str,
    actor: str,
    note: Optional[str] = None,
) -> None:
    """Append one state transition (no commit -- the caller owns the transaction)."""
    conn.execute(
        "INSERT INTO domain_proposal_events "
        "(proposal_id, from_state, to_state, actor, note) "
        "VALUES (%s, %s, %s, %s, %s)",
        (proposal_id, from_state, to_state, actor, note),
    )


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _validate_evidence(evidence: Any) -> None:
    """Refuse an evidence payload that carries no information.

    ``None``, the empty string (or whitespace), and the empty container are
    the same thing from a reviewer's point of view: a claim with nothing
    behind it. Everything else is accepted -- the payload is opaque to this
    layer, only its canonical digest is interpreted.
    """
    if evidence is None:
        raise ValueError("提案必须携带依据")
    if isinstance(evidence, str):
        if not evidence.strip():
            raise ValueError("提案必须携带依据")
        return
    if isinstance(evidence, (dict, list)):
        if not evidence:
            raise ValueError("提案必须携带依据")
        return
    raise ValueError("提案必须携带依据")


class KindNotInVocabulary(ValueError):
    """The kind is outside the domain's anchored vocabulary — a verdict, not damage.

    ``_lane_for_kind`` raises plain ``ValueError`` for three *data* problems
    (anchored template id missing, schema not a dict, no vocabulary declared at
    all); those mean "cannot judge" and the fix belongs to whoever owns the
    template. This subclass is raised for exactly one shape: the template does
    declare a vocabulary, and the kind is in neither list. That one is
    deterministic — confirmation would fail on the same read — so the submit
    side may refuse it.

    Subclassing ``ValueError`` is deliberate: the confirmation path
    (``_write_through_kernel``) and every existing ``except ValueError`` caller
    keep behaving literally as before; only the preflight opts in to the finer
    distinction.
    """


def _lane_for_kind(conn: Any, *, domain: dict, kind: str) -> str:
    """Decide which kernel entry point a proposal kind belongs to.

    The vocabulary is data: it lives on the exact template version the domain
    is anchored to. A kind that is in neither list is refused here, naming both
    vocabularies and the anchored version, before anything is written.
    """
    tmpl = templates.get_template_by_id(conn, template_id=domain["template_id"])
    if tmpl is None:
        raise ValueError(
            f"domain {domain['key']!r} anchors template id "
            f"{domain['template_id']!r}, which does not exist"
        )
    schema = tmpl["schema"]
    if not isinstance(schema, dict):
        raise ValueError(
            f"domain {domain['key']!r} template schema is not a dict; "
            "cannot check the kind vocabulary"
        )
    entity_types = schema.get("entity_types")
    relationship_kinds = schema.get("relationship_kinds")
    entity_types = entity_types if isinstance(entity_types, list) else []
    relationship_kinds = (
        relationship_kinds if isinstance(relationship_kinds, list) else []
    )
    if kind in entity_types:
        return "entity"
    if kind in relationship_kinds:
        return "relationship"
    message = (
        f"kind {kind!r} 不在模板 v{domain['template_version']} 词表内："
        f"entity_types={entity_types}, relationship_kinds={relationship_kinds}"
    )
    # 模板缺失 / schema 不是 dict 是「判不出」（上面两处裸 ValueError，正解是修数据）；
    # 「模板在、schema 正常、这个 kind 两张表都没有」是裁决。空词表这一档不必单列：
    # `templates.validate_template_schema` 要求这两个键存在且为非空列表，所以它在
    # API 面上造不出来；真从旧数据里冒出来时拒绝也是对的——确认走同一张表，照样失败。
    raise KindNotInVocabulary(message)


def _relationship_endpoints(evidence: Any) -> tuple[str, str]:
    """Read the two endpoint keys a relationship confirmation needs.

    The proposal row has no attrs column, so the endpoints travel inside the
    evidence payload (``from_key``/``to_key``; ``from``/``to`` accepted as the
    shorthand). They must be present and non-empty: the kernel derives the
    relationship external key from them, and guessing them is not an option.
    """
    if not isinstance(evidence, dict):
        raise ValueError(
            "relationship 提案的 evidence 必须是对象并携带 from_key/to_key"
        )
    from_key = evidence.get("from_key") or evidence.get("from")
    to_key = evidence.get("to_key") or evidence.get("to")
    if (
        not isinstance(from_key, str)
        or not from_key.strip()
        or not isinstance(to_key, str)
        or not to_key.strip()
    ):
        raise ValueError(
            "relationship 提案的 evidence 缺少非空的 from_key/to_key 端点"
        )
    return from_key, to_key


class ProposalTargetExists(ValueError):
    """The submission targets something the inbox cannot land as a new row.

    Two deterministic shapes, both discovered at submit time by **the same reads
    confirmation uses** (not by a second opinion that could drift):

    - ``key_already_live``: the key is already a live unit in this domain.
      Confirmation goes through the kernel's unit upsert, so landing it would
      *rewrite that unit's body*. The submitter cannot see this from its side,
      and a reviewer approving it reads "add" while performing "overwrite" —
      measured 2026-11-15: 8 of the 41 rejected proposals in ``legal`` were
      exactly this, each caught by a human hand.
    - ``endpoints_missing``: a relationship needs both endpoints live; the box
      does not create them, so confirmation is guaranteed to fail (4 more).

    Semantic judgements — a 文种名 that cannot be reused, a body with no
    principle worth keeping — are deliberately **not** here. Those are the
    domain owner's call; a machine rule that guessed them would be wrong in a
    way nobody reviews.

    ``reason`` is the machine-readable word the HTTP face returns; ``hint``
    names the legitimate path so the caller fixes the right thing.
    """

    def __init__(
        self, reason: str, *, external_key: str, detail: str, hint: str
    ) -> None:
        self.reason = reason
        self.external_key = external_key
        self.detail = detail
        self.hint = hint
        super().__init__(f"{detail}；{hint}")


def preflight_targets(
    conn: Any,
    *,
    domain: dict,
    kind: str,
    external_key: str,
    evidence: Any,
) -> None:
    """Refuse a submission the ontology cannot accept, before it consumes a slot.

    The two reads are the confirmation path's own: ``_lane_for_kind`` (which
    vocabulary the kind belongs to, from the domain's anchored template) and
    ``authoring_live_key_kinds`` / ``authoring_get_unit`` (the live-unit set).
    Nothing here writes, and nothing here invents a third notion of "exists" —
    a preflight with its own lookup would refuse what confirmation accepts (a
    false red, worse than a false green: it teaches the fleet to stop
    submitting legitimate content).

    Soft-deleted keys are *not* live, matching ``authoring_live_keys``.

    A relationship's endpoint counts as "will exist" if it is already live **or
    already pending in this same inbox**: the in-process extractor submits an
    entity and the relationship that closes on it in one batch, and at that
    instant the endpoint is a pending row, not a unit. Refusing that shape would
    break exactly the flow the box was built for (measured 2026-11-15: the
    ``same batch entity closes the endpoint`` case). The reviewer still decides
    both, and confirming the relationship before the entity fails in the kernel
    as it always did.

    A ``kind`` that the anchored template does not declare is refused here too
    (``KindNotInVocabulary``): confirmation reads the same vocabulary, so that
    proposal can never land — waiting for the reviewer to discover it only
    occupies a confirmation slot. A template that declares **no** vocabulary is
    a different shape (nothing to judge against, and the fix is template data,
    not the submitter's), so it still returns.
    """
    try:
        lane = _lane_for_kind(conn, domain=domain, kind=kind)
    except KindNotInVocabulary as exc:
        raise ProposalTargetExists(
            "kind_not_in_vocabulary",
            external_key=external_key,
            detail=f"{exc}（模板 v{domain['template_version']} 是该域锚定的词表来源）",
            hint=(
                "改用词表内的 kind 重提；若这个 kind 本来就该被接受，"
                "那是一次治理动作——由域负责人扩模板词表，而不是在提交口绕过"
            ),
        ) from exc
    except ValueError:
        return
    live = authoring.authoring_live_key_kinds(conn, domain_key=domain["key"])
    pending = {
        row["external_key"]
        for row in conn.execute(
            "SELECT external_key FROM domain_proposals "
            "WHERE domain_id = %s AND state = 'pending'",
            (domain["id"],),
        ).fetchall()
    }
    known = set(live) | pending

    if lane == "relationship":
        from_key, to_key = _relationship_endpoints(evidence)
        missing = [key for key in (from_key.strip(), to_key.strip()) if key not in known]
        if missing:
            raise ProposalTargetExists(
                "endpoints_missing",
                external_key=external_key,
                detail=f"关系端点既不在本域活单位里、也不在本域提案箱里：{', '.join(missing)}",
                hint=(
                    "提案箱不替关系造端点：先提交缺的端点（实体提案），或先确认它，"
                    "再提交这条关系"
                ),
            )
        return

    existing_kind = live.get(external_key)
    if existing_kind is None:
        return
    row = authoring.authoring_get_unit(
        conn, domain_key=domain["key"], kind=existing_kind, external_key=external_key
    )
    if row is None:  # pragma: no cover - the set and the single read agree
        return
    if (row.get("tags") or {}).get("deleted"):
        return  # 软删的不算活单位：与 live 集合一致
    unit_id = row.get("id")
    if existing_kind == kind:
        detail = (
            f"键 {external_key!r} 在本域已是活单位（id={unit_id}, kind={existing_kind}）："
            "确认这条提案会改写那条单位的正文"
        )
    else:
        detail = (
            f"键 {external_key!r} 在本域已作为 kind={existing_kind} 的活单位存在"
            f"（id={unit_id}）：同一键再以 kind={kind} 提交会造出同键两条单位"
        )
    raise ProposalTargetExists(
        "key_already_live",
        external_key=external_key,
        detail=detail,
        hint="要改既有单位请走更新（控制台的单位编辑），不要用新建提案覆盖它",
    )


def _write_through_kernel(
    conn: Any, *, domain: dict, proposal: dict, actor: str
) -> dict:
    """Confirm time is the only ontology write, and it goes through the kernel.

    No SQL against ``knowledge_units`` exists in this module by design: the
    kernel gates the vocabulary, writes the KU in the domain namespace, and
    appends the ``authoring_events`` row. The kernel commits on its own, so the
    caller updates the proposal row only after this returns.
    """
    kind = proposal["kind"]
    if _lane_for_kind(conn, domain=domain, kind=kind) == "relationship":
        from_key, to_key = _relationship_endpoints(proposal["evidence"])
        attrs = proposal["evidence"].get("attrs")
        return authoring.authoring_create_relationship(
            conn,
            domain_key=domain["key"],
            kind=kind,
            from_key=from_key,
            to_key=to_key,
            body=proposal["body"],
            operator=actor,
            attrs=attrs if isinstance(attrs, dict) else None,
        )
    return authoring.authoring_create_unit(
        conn,
        domain_key=domain["key"],
        kind=kind,
        external_key=proposal["external_key"],
        body=proposal["body"],
        operator=actor,
    )


# ------------------------------------------------------------------- digest


def canonical_evidence_digest(evidence: dict | list | str) -> str:
    """Sha256 of the evidence's canonical JSON form — one definition, in the kernel.

    Key order never changes the digest, so two processes (or two submissions
    months apart) always agree on whether evidence is "the same".
    """
    return kernel_proposals.evidence_digest(evidence)


# ------------------------------------------------------------------ workflow


def submit(
    conn: Any,
    *,
    domain_key: str,
    source: str,
    kind: str,
    external_key: str,
    body: str,
    evidence: Any,
    impact: str = "",
    submitted_by: str,
    with_created: bool = False,
    via: str = submitters.VIA_HTTP,
    authenticated_as: Optional[str] = None,
):
    """Submit one proposal into the domain's inbox, or return the open one.

    The pending row for ``(domain, source, external_key)`` is the submission's
    identity: a repeat submission returns it untouched (evidence included), so
    the inbox cannot grow duplicates. A *rejected* row is history, not an
    identity: resubmitting the same key is allowed only with different
    evidence, which is the "new evidence required" rule expressed as a digest
    comparison. Returns the stored proposal dict.

    ``with_created=True`` returns ``(proposal, created)`` instead. An idempotent
    hit must be tellable apart from a new row: the submitting fleet reports
    「新增」 vs 「幂等命中」 to its operator, and a report that cannot tell the
    two apart is not a report.

    ``via`` is the caller's own channel. It matters: ``extract:`` sources are
    accepted only for ``in_process``, because their whole trust basis is that
    the extraction pipeline is not reachable over the network. A caller that
    forgets to pass it gets the external (stricter) rule, which fails loudly
    instead of silently trusting a self-declared pipeline.
    """
    domain = _load_domain(conn, domain_key=domain_key)

    verdict = distribution.resolve_submitter(
        conn,
        source=source,
        domain_key=domain_key,
        via=via,
        authenticated_as=authenticated_as,
    )[1]
    mode = _submitter_mode()
    if verdict != "ok":
        if verdict in _NEVER_TOLERATED or mode == MODE_STRICT:
            raise SubmitterRefused(verdict, source=source, domain_key=domain_key)
        # Lenient migration window: the row lands, the verdict is recorded so
        # the count can be read and driven to zero before the window closes.

    _validate_evidence(evidence)
    _require_text(kind, "kind")
    _require_text(external_key, "external_key")
    _require_text(body, "body")

    # 与内核写入口同一把尺子：键在这里先归名，否则提案箱会把同一个实体的两种写法
    # 存成两条，人确认完才发现本体里也是两条。提案行没有 attrs 列，所以原写法记进
    # impact（人读的那一栏），不吞掉。
    raw_key = external_key.strip()
    rules = keys.rules_for(domain.get("key") or "")
    if rules:
        folded_key, applied = keys.fold(raw_key, rules)
        folded_key = (folded_key or "").strip() or raw_key
        if folded_key != raw_key:
            external_key = folded_key
            note = f"键已归名：{raw_key} → {folded_key}（规则 {', '.join(applied)}）"
            impact = f"{note}；{impact}".strip("；") if impact else note

    digest = canonical_evidence_digest(evidence)

    # ① 先按**主张**去重（同键 + 同依据）：舰队的提案岗与应用内岗位可能同时提出
    # 同一条主张，过去的去重身份含 source，于是会变成两行待确认——人眼只有一双。
    # 命中时把新的提交方并入 sources，source 保留首个提交方（谁先说的）。
    claim = conn.execute(
        f"SELECT {_PROPOSAL_COLS} FROM domain_proposals "
        "WHERE domain_id = %s AND external_key = %s AND evidence_digest = %s "
        "AND state = 'pending' LIMIT 1",
        (domain["id"], external_key, digest),
    ).fetchone()
    if claim is not None:
        existing = _proposal_to_dict(claim)
        sources = list(existing.get("sources") or [])
        if existing["source"] not in sources:
            sources.insert(0, existing["source"])
        if source not in sources:
            sources.append(source)
            conn.execute(
                "UPDATE domain_proposals SET sources = %s::jsonb WHERE id = %s",
                (json.dumps(sources, ensure_ascii=False), existing["id"]),
            )
            conn.commit()
        existing["sources"] = sources
        return (existing, False) if with_created else existing

    # ② 同一提交方的重复提交（原有语义，保留）
    pending = conn.execute(
        f"SELECT {_PROPOSAL_COLS} FROM domain_proposals "
        "WHERE domain_id = %s AND source = %s AND external_key = %s "
        "AND state = 'pending'",
        (domain["id"], source, external_key),
    ).fetchone()
    if pending is not None:
        existing = _proposal_to_dict(pending)
        return (existing, False) if with_created else existing

    same_evidence = conn.execute(
        "SELECT 1 FROM domain_proposals "
        "WHERE domain_id = %s AND source = %s AND external_key = %s "
        "AND state = 'rejected' AND evidence_digest = %s LIMIT 1",
        (domain["id"], source, external_key, digest),
    ).fetchone()
    if same_evidence is not None:
        # Same claim, same evidence, already judged — the one thing a rejection
        # means. The error *type* comes from the kernel (so a caller can branch on
        # PROPOSAL_STALE_EVIDENCE); the message stays this surface's published
        # wording, which the contract-doc test pins.
        raise ProposalStaleEvidence(
            "同键已驳回，需新证据",
            external_key=external_key,
            evidence_digest=digest,
        )

    # ③ 预检：这条提案落不落得下去。排在三条去重之后是纪律——重放必须仍是
    # `created=false`（舰队「新增 vs 幂等命中」的报数基石），预检只回答
    # 「此刻落不落得下去」，不改幂等语义。两类的处置方向不同，所以理由分开：
    # 重复键要改既有的、端点缺失要先补端点。语义类否决权仍归人，不在这里。
    preflight_targets(
        conn, domain=domain, kind=kind, external_key=external_key, evidence=evidence
    )

    cur = conn.execute(
        f"INSERT INTO domain_proposals "
        f"(domain_id, source, sources, kind, external_key, body, evidence, "
        f"evidence_digest, impact, state, submitted_by, submitter_verdict) "
        f"VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, 'pending', %s, %s) "
        f"RETURNING {_PROPOSAL_COLS}",
        (
            domain["id"],
            source,
            json.dumps([source], ensure_ascii=False),
            kind,
            external_key,
            body,
            json.dumps(evidence),
            digest,
            impact,
            submitted_by,
            verdict,
        ),
    )
    proposal = _proposal_to_dict(cur.fetchone())
    _record_event(
        conn,
        proposal_id=proposal["id"],
        from_state=None,
        to_state="pending",
        actor=submitted_by,
    )
    conn.commit()
    return (proposal, True) if with_created else proposal


def confirm(
    conn: Any,
    *,
    domain_key: str,
    proposal_id: int,
    actor: str,
    admin_override: bool = False,
) -> dict:
    """Accept a proposal and write its content through the kernel.

    A confirmed proposal is a completed decision, so confirming it again is
    idempotent: the same row is returned and neither the kernel nor the event
    trail is touched a second time. A rejected proposal cannot be confirmed
    (the submitter must resubmit with new evidence instead), and a submitter
    cannot confirm their own proposal unless an admin explicitly overrides.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    proposal = _load_proposal(conn, domain_id=domain["id"], proposal_id=proposal_id)
    if proposal is None:
        raise ValueError(f"proposal {proposal_id} not found in domain {domain_key!r}")

    if proposal["state"] == "confirmed":
        return proposal
    if proposal["state"] != "pending":
        raise ValueError(
            f"proposal {proposal_id} is {proposal['state']!r}, not 'pending'; "
            "a rejected proposal must be resubmitted with new evidence"
        )

    # 两道机器身份闸，顺序重要：先拦「机器当签字人」，再拦「管理员豁免替机器背书」。
    #
    # 第一道覆盖**任何机器形状的身份**，不只是 agent：硬停清单里 confirm 不发给机器，
    # 这一道是内核侧的兜底（工具面没有那个动词，但内核不能假设调用方一定经过工具面）。
    # 2026-11-14 这里只判 `is_agent`（只认 `agent:` 前缀），于是 `fleet:` 形状的字符串
    # 能签字——产库上 `actor="fleet:probe"` 一次就通过了，写出了一条单元并留下那条
    # operator。机器身份的类别前缀现在集中在 `agent_ids.MACHINE_PREFIXES`。
    if agent_ids.is_machine(actor):
        raise PermissionError("机器身份不得确认提案；确认是人类 lead 的职责")
    # 第二道堵 admin 豁免：豁免的存在是给人救火用的，一旦它能替机器提交的提案背书，
    # `admin` scope 就等于一张自签通行证。所以只要提交方是机器身份，豁免一律不生效
    # ——人工 lead 正常确认（submitted_by != actor）仍然可以。
    if admin_override and agent_ids.is_machine(proposal["submitted_by"]):
        raise PermissionError(
            "管理员豁免不适用于机器身份提交的提案；请由人类负责人正常确认"
        )
    if proposal["submitted_by"] == actor and not admin_override:
        raise PermissionError("提案人不得自提自确认")

    _write_through_kernel(conn, domain=domain, proposal=proposal, actor=actor)

    # The tag records a waiver that actually happened: an admin confirming a
    # proposal THEY submitted. An admin confirming someone else's proposal never
    # met the separation-of-duties rule, so no tag is written — a note claiming
    # an override that did not occur is a false audit trail.
    waived = admin_override and proposal["submitted_by"] == actor
    note = (
        f"{_ADMIN_OVERRIDE_TAG} confirmed by admin over the submitter "
        f"{proposal['submitted_by']!r}"
        if waived
        else ""
    )
    cur = conn.execute(
        f"UPDATE domain_proposals SET state = 'confirmed', decided_by = %s, "
        f"decided_at = now(), decision_note = %s "
        f"WHERE id = %s AND domain_id = %s AND state = 'pending' "
        f"RETURNING {_PROPOSAL_COLS}",
        (actor, note, proposal_id, domain["id"]),
    )
    updated = cur.fetchone()
    if updated is None:
        raise ValueError(
            f"proposal {proposal_id} changed state while being confirmed"
        )
    _record_event(
        conn,
        proposal_id=proposal_id,
        from_state="pending",
        to_state="confirmed",
        actor=actor,
        note=note or None,
    )
    conn.commit()
    return _proposal_to_dict(updated)


def reject(
    conn: Any, *, domain_key: str, proposal_id: int, actor: str, note: str
) -> dict:
    """Reject a pending proposal; the reason is part of the record.

    A bare rejection is not actionable for the submitter, so ``note`` is
    mandatory. Rejecting an already-rejected proposal returns it unchanged
    (no second event); a confirmed proposal cannot be rejected -- that would
    rewrite a decision whose content is already in the ontology.
    """
    if not isinstance(note, str) or not note.strip():
        raise ValueError("驳回必须写明理由")

    domain = _load_domain(conn, domain_key=domain_key)
    proposal = _load_proposal(conn, domain_id=domain["id"], proposal_id=proposal_id)
    if proposal is None:
        raise ValueError(f"proposal {proposal_id} not found in domain {domain_key!r}")

    if proposal["state"] == "rejected":
        return proposal
    if proposal["state"] != "pending":
        raise ValueError(
            f"proposal {proposal_id} is {proposal['state']!r}, not 'pending'; "
            "a confirmed proposal cannot be rejected"
        )

    cur = conn.execute(
        f"UPDATE domain_proposals SET state = 'rejected', decided_by = %s, "
        f"decided_at = now(), decision_note = %s "
        f"WHERE id = %s AND domain_id = %s AND state = 'pending' "
        f"RETURNING {_PROPOSAL_COLS}",
        (actor, note, proposal_id, domain["id"]),
    )
    updated = cur.fetchone()
    if updated is None:
        raise ValueError(
            f"proposal {proposal_id} changed state while being rejected"
        )
    _record_event(
        conn,
        proposal_id=proposal_id,
        from_state="pending",
        to_state="rejected",
        actor=actor,
        note=note,
    )
    conn.commit()
    return _proposal_to_dict(updated)


# ---------------------------------------------------------------- read side


def batches(conn: Any, *, domain_key: str) -> list[dict]:
    """Distinct extraction batches in this domain, newest first, with counts."""
    domain = _load_domain(conn, domain_key=domain_key)
    rows = conn.execute(
        "SELECT evidence->>'batch' AS batch, state, COUNT(*) AS n "
        "FROM domain_proposals WHERE domain_id = %s AND evidence ? 'batch' "
        "GROUP BY 1, 2 ORDER BY 1 DESC",
        (domain["id"],),
    ).fetchall()
    rates = {
        r["batch"]: r["rate"]
        for r in conn.execute(
            "SELECT evidence->>'batch' AS batch, MAX(evidence->>'usable_rate') AS rate "
            "FROM domain_proposals WHERE domain_id = %s AND evidence ? 'usable_rate' "
            "GROUP BY 1",
            (domain["id"],),
        ).fetchall()
    }
    merged: dict[str, dict] = {}
    for row in rows:
        name = row["batch"]
        if not name:
            continue
        entry = merged.setdefault(name, {"batch": name, "pending": 0, "confirmed": 0,
                                         "rejected": 0, "total": 0,
                                         "usable_rate": None, "low_yield": False})
        entry[row["state"]] = row["n"]
        entry["total"] += row["n"]
    for name, entry in merged.items():
        raw = rates.get(name)
        if raw:
            try:
                entry["usable_rate"] = float(raw)
                entry["low_yield"] = entry["usable_rate"] < 0.5
            except (TypeError, ValueError):
                pass
    return [merged[k] for k in sorted(merged, reverse=True)]


def list_outcomes(
    conn: Any, *, source: str, domain_key: Optional[str] = None, limit: int = 200
) -> list[dict]:
    """Proposals this submitter has a stake in, with the decision trail.

    "Has a stake in" means ``sources`` contains it — a claim filed by two
    producers is one row, and both of them must be able to read how it ended.
    The row's own ``decision_note`` is the rejection reason the operator typed;
    it is projected verbatim, never summarised: a submitter that is told
    "rejected" without the reason can only guess what to fix.

    A caller MUST pass its own resolved ``source``; isolation is the caller's
    job (the route resolves the submitter first), and this function trusts the
    argument to be that identity.
    """
    ref = (source or "").strip()
    if not ref:
        raise ValueError("source is required")
    sql = (
        f"SELECT p.{', p.'.join(_PROPOSAL_KEYS)}, d.key AS domain_key "
        "FROM domain_proposals p JOIN domains d ON d.id = p.domain_id "
        "WHERE p.sources @> %s::jsonb"
    )
    params: list[Any] = [json.dumps([ref], ensure_ascii=False)]
    if domain_key:
        sql += " AND d.key = %s"
        params.append(domain_key)
    sql += " ORDER BY p.submitted_at DESC, p.id DESC LIMIT %s"
    params.append(max(1, min(int(limit or 200), 500)))

    out: list[dict] = []
    for row in conn.execute(sql, tuple(params)).fetchall():
        item = _proposal_to_dict(row)
        item["domain_key"] = row["domain_key"]
        out.append(item)
    return out


def legacy_sources(conn: Any, *, verdict: Optional[str] = None) -> list[dict]:
    """Sources admitted by the lenient window, with counts, worst first.

    This is the read surface that decides when the window can close: the answer
    must be a count of rows whose recorded verdict is not ``ok``, grouped by
    source — not a guess from the shape of the string.

    ``NULL`` verdicts are rows written before the column existed; they are the
    one group that cannot be re-judged after the fact, so they are reported
    separately rather than folded into a verdict bucket.
    """
    sql = (
        "SELECT source, submitter_verdict, count(*) AS n "
        "FROM domain_proposals "
        "WHERE submitter_verdict IS DISTINCT FROM 'ok' "
    )
    params: list[Any] = []
    if verdict is not None:
        sql += "AND submitter_verdict IS NOT DISTINCT FROM %s "
        params.append(verdict)
    sql += "GROUP BY source, submitter_verdict ORDER BY n DESC, source"
    cur = conn.execute(sql, tuple(params))
    return [
        {"source": r["source"], "verdict": r["submitter_verdict"], "n": r["n"]}
        for r in cur.fetchall()
    ]


def list_proposals(
    conn: Any,
    *,
    domain_key: str,
    state: Optional[str] = None,
    batch: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """The domain's inbox, newest submission first.

    ``batch`` filters on ``evidence->>'batch'`` — extraction files its output in
    named batches so a reviewer can work through one run at a time instead of
    whatever happens to be newest.
    """
    if state is not None and state not in PROPOSAL_STATES:
        raise ValueError(f"state must be one of {list(PROPOSAL_STATES)}")
    domain = _load_domain(conn, domain_key=domain_key)
    where, params = ["domain_id = %s"], [domain["id"]]
    if state is not None:
        where.append("state = %s")
        params.append(state)
    if batch:
        where.append("evidence->>'batch' = %s")
        params.append(batch)
    params.append(limit)
    cur = conn.execute(
        f"SELECT {_PROPOSAL_COLS} FROM domain_proposals "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY submitted_at DESC, id DESC LIMIT %s",
        params,
    )
    return [_proposal_to_dict(r) for r in cur.fetchall()]


def get(conn: Any, *, domain_key: str, proposal_id: int) -> Optional[dict]:
    """Fetch one proposal in the domain's inbox; ``None`` when out of scope."""
    domain = _load_domain(conn, domain_key=domain_key)
    return _load_proposal(conn, domain_id=domain["id"], proposal_id=proposal_id)


def describe_sources(
    conn: Any, *, sources: Iterable[Any], domain_key: str
) -> dict[str, dict]:
    """Resolve submission sources into what a reviewer needs to see.

    A raw ``fleet:<id>/<post>`` string tells a reviewer nothing: which fleet, does
    it still exist, and is this post one we recognise? So the inbox shows the
    *resolved* form — registration name plus post id, or the raw string with a
    ``legacy`` mark when nothing resolves. The mark matters more than the name:
    an unresolved source is a row whose submitter cannot be held to anything, and
    silently rendering it as if it were normal hides exactly that.

    One lookup per distinct source (the inbox holds dozens, not thousands), and
    the same classifier the submission gate uses, so the page cannot disagree
    with what would be accepted today.
    """
    from . import distribution, submitters

    wanted = []
    for value in sources:
        text = (value or "").strip()
        if text and text not in wanted:
            wanted.append(text)

    out: dict[str, dict] = {}
    for text in wanted:
        prefix, parts, malformed = submitters.classify_source(text)
        view = {
            "raw": text,
            "class": (prefix or "").rstrip(":") or "unknown",
            "post_id": None,
            "fleet_ref": None,
            "fleet_name": None,
            "registered": False,
            "legacy": True,
        }
        if prefix == submitters.PREFIX_FLEET and parts and not malformed:
            consumer, verdict = distribution.resolve_submitter(
                conn, source=text, domain_key=domain_key, via=submitters.VIA_IN_PROCESS
            )
            view["fleet_ref"] = parts["fleet_id"]
            view["post_id"] = parts["post_id"]
            view["fleet_name"] = (consumer or {}).get("name")
            view["registered"] = verdict == "ok"
            view["legacy"] = verdict != "ok"
            view["verdict"] = verdict
        elif prefix != submitters.PREFIX_FLEET:
            # 非舰队来源没有登记可查；能判它「不是遗留」的依据是它能被判成立。
            view["legacy"] = not submitters.is_allowed(
                submitters.verdict(
                    text, domain_key=domain_key, via=submitters.VIA_IN_PROCESS
                )
            )
        out[text] = view
    return out


def count_pending(conn: Any, *, domain_key: str) -> int:
    """How many proposals await a decision (the inbox badge)."""
    domain = _load_domain(conn, domain_key=domain_key)
    value = _scalar(
        conn.execute(
            "SELECT COUNT(*) AS pending_count FROM domain_proposals "
            "WHERE domain_id = %s AND state = 'pending'",
            (domain["id"],),
        ).fetchone()
    )
    return int(value or 0)


def events_for(conn: Any, *, proposal_id: int) -> list[dict]:
    """The proposal's transition trail, oldest first (replay order)."""
    cur = conn.execute(
        f"SELECT {_EVENT_COLS} FROM domain_proposal_events "
        "WHERE proposal_id = %s ORDER BY happened_at ASC, id ASC",
        (proposal_id,),
    )
    return [_event_to_dict(r) for r in cur.fetchall()]
