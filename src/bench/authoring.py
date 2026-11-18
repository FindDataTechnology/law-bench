"""Expert authoring entry points over the kernel knowledge-unit store.

Every authoring write goes through :func:`src.bench.store.upsert_knowledge_unit`
(the single ontology write path): the domain key is the KU namespace, the kind
is gated against the vocabulary of the exact template version the domain is
anchored to, the first tier is ``raw``, and the operator lands in the
provenance. Each write appends one row to ``authoring_events`` (append-only:
no code path ever updates or deletes an event row), so the change trail stays
replayable.

Domain isolation is enforced here, at the entry points: every write and read
first resolves the domain (unknown key refused), then uses its key as the
namespace, so cross-domain content can never leak through this module.

Key conventions locked in this module are distribution-contract anchors:

- ``RELATIONSHIP_KEY_TEMPLATE`` is the deterministic external-key convention
  for relationship units. Downstream publishing consumers derive relationship
  identity from this key; changing it breaks identity alignment with
  already-published data.

Style: borrowed connection (never opened or closed here), ``%s`` placeholders,
one ``conn.commit()`` at the end of each write, JSONB via ``json.dumps``/
``json.loads``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from . import keys, store, templates, workspaces

# Distribution-contract anchor (see module docstring): the deterministic
# external-key convention for relationship units. Do not change it.
RELATIONSHIP_KEY_TEMPLATE = "{from_key}->{kind}:{to_key}"

# Vocabularies mirrored by the CHECK constraints on authoring_events /
# authoring_tasks (see src/bench/workspace_store.py::WORKSPACE_SCHEMA).
EVENT_OPS = ("create", "update", "delete")
TASK_STATUSES = ("pending", "in_progress", "done", "cancelled")

_EVENT_COLS = (
    "id, domain_id, unit_kind, unit_key, op, before, after, operator, via, created_at"
)
_EVENT_KEYS = (
    "id",
    "domain_id",
    "unit_kind",
    "unit_key",
    "op",
    "before",
    "after",
    "operator",
    "via",
    "created_at",
)

_TASK_COLS = (
    "id, domain_id, assignee, title, detail, target_kind, target_key, "
    "status, transitions, created_by, created_at, updated_at, "
    "assignee_kind, assignee_ref"
)

#: 三档指派人。``human`` 的引用是被授权的人身份；``kernel-role`` 是岗位词表内的
#: 名字；``fleet`` 是一条已登记且绑定本域的舰队登记引用。把「展示成什么」与
#: 「授权给谁」分开，是这个枚举存在的唯一理由。
ASSIGNEE_KINDS: tuple[str, ...] = ("human", "kernel-role", "fleet")
_TASK_KEYS = (
    "id",
    "domain_id",
    "assignee",
    "title",
    "detail",
    "target_kind",
    "target_key",
    "status",
    "transitions",
    "created_by",
    "created_at",
    "updated_at",
    "assignee_kind",
    "assignee_ref",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(val: Any) -> Any:
    """Return a consistent ISO-8601 string for driver timestamps; pass text through."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _decode_jsonb(val: Any) -> Any:
    if isinstance(val, (dict, list)) or val is None:
        return val
    return json.loads(val)


def _copy_unit(unit: dict) -> dict:
    """Deep-ish copy of a KU dict (JSON round-trip) so an event snapshot can
    never alias the live row dict."""
    return json.loads(json.dumps(unit))


def _event_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _EVENT_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "domain_id": values[1],
        "unit_kind": values[2],
        "unit_key": values[3],
        "op": values[4],
        "before": _decode_jsonb(values[5]),
        "after": _decode_jsonb(values[6]),
        "operator": values[7],
        "via": values[8],
        "created_at": _iso(values[9]),
    }


def _task_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _TASK_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "domain_id": values[1],
        "assignee": values[2],
        "title": values[3],
        "detail": values[4],
        "target_kind": values[5],
        "target_key": values[6],
        "status": values[7],
        "transitions": _decode_jsonb(values[8]),
        "created_by": values[9],
        "created_at": _iso(values[10]),
        "updated_at": _iso(values[11]),
        "assignee_kind": values[12] or "human",
        "assignee_ref": values[13],
    }


# ------------------------------------------------------------------ helpers


def _load_domain(conn: Any, *, domain_key: str) -> dict:
    """Resolve the domain or refuse the operation (fail-closed isolation)."""
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"domain {domain_key!r} not found")
    return domain


def _gate_kind(conn: Any, *, domain: dict, kind: str, vocab_key: str) -> None:
    """Check ``kind`` against the domain's anchored template vocabulary.

    The vocabulary lives in the domain's data (the template row the domain was
    instantiated from); this gate only reads it, it does not own it.
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
            f"cannot check the {vocab_key} vocabulary"
        )
    vocab = schema.get(vocab_key)
    if not isinstance(vocab, list) or not vocab:
        raise ValueError(
            f"domain {domain['key']!r} template schema has no usable "
            f"{vocab_key} vocabulary"
        )
    if kind not in vocab:
        raise ValueError(
            f"kind {kind!r} is not in the {vocab_key} vocabulary of domain "
            f"{domain['key']!r}; allowed kinds: {vocab}"
        )


def _vocabulary(conn: Any, *, domain: dict, key: str) -> list[str]:
    """The declared vocabulary list for ``key`` (``[]`` when unusable).

    Read-only sibling of :func:`_gate_kind`: the pickers and the importer need
    the list itself, not a pass/fail verdict, and they must read it from the
    same template row the gate uses.
    """
    tmpl = templates.get_template_by_id(conn, template_id=domain["template_id"])
    schema = (tmpl or {}).get("schema") or {}
    vocab = schema.get(key) if isinstance(schema, dict) else None
    return [str(v) for v in vocab] if isinstance(vocab, list) else []


def _record_event(
    conn: Any,
    *,
    domain_id: int,
    unit_kind: str,
    unit_key: str,
    op: str,
    before: Optional[dict],
    after: Optional[dict],
    operator: str,
    via: str = "authoring",
) -> dict:
    """Append one change event (no commit -- the caller owns the transaction)."""
    cur = conn.execute(
        f"INSERT INTO authoring_events "
        f"(domain_id, unit_kind, unit_key, op, before, after, operator, via) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_EVENT_COLS}",
        (
            domain_id,
            unit_kind,
            unit_key,
            op,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            operator,
            via,
        ),
    )
    return _event_to_dict(cur.fetchone())


def _fold_write_key(
    *, domain: dict, external_key: str, attrs: Optional[dict]
) -> tuple[str, Optional[dict]]:
    """把写入的键按该域已注册的规则归名（写入边界，不是调用方各自负责）。

    为什么在这里：归名过去只发生在两个调用方（取目录 ``corpus_catalog`` 与抽取
    ``extraction``），而 ``authoring_create_unit`` / 提案确认 / 批量导入都原样落库。
    结果是同一个实体两个键，两条都进本体——2026-11-09 实测有一批 401 条单位因为
    父键未归名而全部要退掉重来。写入方一多（舰队 + 七个岗位），
    "记得 import pack" 必然失效，所以把规则下沉到唯一写入口。

    三条纪律：

    - 该域没有注册规则 → **不归名**（安全默认：宁可少合并，不可凭空合并）；
    - 归名后与原写法不同 → 原写法进 ``attrs.aliases``，并记下生效的规则名，
      使合并可解释；
    - 归名结果为空（规则把整串吃掉了）→ 退回原写法，绝不写空键。
    """
    raw = (external_key or "").strip()
    if not raw:
        return raw, attrs
    rules = keys.rules_for(domain.get("key") or "")
    if not rules:
        return raw, attrs
    folded, applied = keys.fold(raw, rules)
    folded = (folded or "").strip()
    if not folded or folded == raw:
        return raw, attrs
    merged = dict(attrs or {})
    aliases = set(merged.get("aliases") or [])
    aliases.add(raw)
    merged["aliases"] = sorted(aliases)
    merged["folded_by"] = list(applied)
    return folded, merged


def _create_unit(
    conn: Any,
    *,
    domain: dict,
    kind: str,
    external_key: str,
    body: str,
    operator: str,
    tags: Optional[dict],
    attrs: Optional[dict],
    vocab_key: str,
) -> dict:
    """Shared create path: delegate to the kernel's single write path.

    The kernel does the four things this function used to do inline — vocabulary
    gate, write-boundary folding, unit upsert, paired event — so the mechanism
    exists once. What stays here is the surface's own detail: which connection,
    which provenance, and returning the stored row in the shape callers expect.

    **The whole write is one transaction.** The kernel cannot open one; the
    adapter must, or an event failure would leave a content change with no
    audit row.
    """
    from . import kernel_ports

    kernel = kernel_ports.kernel_for(conn, domain=domain)
    with conn.transaction():
        written = kernel.write(
            scope_id=domain["key"],
            kind=kind,
            external_key=external_key,
            body=body,
            actor=operator,
            via="authoring",
            tags=tags,
            attrs=attrs,
            tier="raw",
            provenance={"operator": operator},
            vocab_name=vocab_key,
        )
    row = store.get_knowledge_unit(
        conn,
        kind=kind,
        external_key=written.unit.external_key,
        namespace=domain["key"],
    )
    if row is None:  # pragma: no cover - the write just succeeded in this tx
        raise RuntimeError(
            f"unit {kind!r}/{written.unit.external_key!r} vanished after a successful write"
        )
    return row


def _soft_delete_unit(
    conn: Any, *, domain: dict, kind: str, external_key: str, operator: str
) -> dict:
    """Shared delete path: the kernel flags the unit and journals a ``delete``.

    Content and metadata are preserved unchanged so the event stream stays
    replayable; only ``tags["deleted"]`` and the provenance stamp move.
    """
    from . import kernel_ports

    kernel = kernel_ports.kernel_for(conn, domain=domain)
    with conn.transaction():
        written = kernel.remove(
            scope_id=domain["key"],
            kind=kind,
            external_key=external_key,
            actor=operator,
            via="authoring",
        )
    row = store.get_knowledge_unit(
        conn,
        kind=kind,
        external_key=written.unit.external_key,
        namespace=domain["key"],
    )
    if row is None:  # pragma: no cover
        raise RuntimeError("unit vanished after a successful soft delete")
    return row


# -------------------------------------------------------------------- units


def authoring_create_unit(
    conn: Any,
    *,
    domain_key: str,
    kind: str,
    external_key: str,
    body: str,
    operator: str,
    tags: Optional[dict] = None,
    attrs: Optional[dict] = None,
) -> dict:
    """Create (or, if the key already exists, effectively update) one unit.

    The kind must be in the domain's ``entity_types`` vocabulary; anything
    else is refused with the allowed vocabulary named, before anything is
    written (no KU, no event). Returns the stored KU dict.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    return _create_unit(
        conn,
        domain=domain,
        kind=kind,
        external_key=external_key,
        body=body,
        operator=operator,
        tags=tags,
        attrs=attrs,
        vocab_key="entity_types",
    )


def authoring_create_units(
    conn: Any,
    *,
    domain_key: str,
    units: list[dict],
    operator: str,
) -> list[dict]:
    """Create many units in **one** transaction: all of them or none.

    ``authoring_create_unit`` commits per unit, which is right for a human
    editing one row and wrong for a batch read out of a corpus: half a document's
    articles in the ontology is a state nobody asked for and nobody can explain
    afterwards. Here every kind is gated before the first write, all rows share
    one transaction, and a failure anywhere rolls the whole batch back.

    Each unit is ``{kind, external_key, body, tags?, attrs?}``. Duplicate keys
    inside one batch are refused up front — two rows writing the same key would
    make "which one landed" depend on ordering.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    if not units:
        return []
    # Fold first, then dedupe: two rows whose keys fold to the same identity are
    # one row, and the duplicate must be caught before anything is written.
    folded: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for unit in units:
        kind, key = unit.get("kind"), unit.get("external_key")
        if not kind or not key:
            raise ValueError("every unit needs both 'kind' and 'external_key'")
        key, attrs = _fold_write_key(
            domain=domain, external_key=key, attrs=unit.get("attrs")
        )
        if (kind, key) in seen:
            raise ValueError(f"duplicate key in one batch: {kind!r}/{key!r}")
        seen.add((kind, key))
        _gate_kind(conn, domain=domain, kind=kind, vocab_key="entity_types")
        folded.append({**unit, "external_key": key, "attrs": attrs})
    units = folded

    written: list[dict] = []
    # 2026-11-09 修正（审计 03 §2/§8）：连接是 autocommit=True，psycopg 3 里
    # commit()/rollback() 在 IDLE 状态是 no-op。原来的「末尾 commit + 失败 rollback」
    # 是空话——中途失败会留下半批已经落库的行，与这个函数承诺的 all-or-none 相反。
    #
    # 现在每行都走内核的唯一写入口；批次事务仍由这里持有，所以「半批落库」不可能
    # 出现——内核不会自己开事务，也就不会把批次切成一个个小事务。
    from . import kernel_ports

    kernel = kernel_ports.kernel_for(conn, domain=domain)
    with conn.transaction():
        for unit in units:
            kernel.write(
                scope_id=domain["key"],
                kind=unit["kind"],
                external_key=unit["external_key"],
                body=unit.get("body") or "",
                actor=operator,
                via="authoring",
                tags=unit.get("tags"),
                attrs=unit.get("attrs"),
                tier="raw",
                provenance={"operator": operator},
                vocab_name="entity_types",
            )
            row = store.get_knowledge_unit(
                conn, kind=unit["kind"], external_key=unit["external_key"],
                namespace=domain["key"],
            )
            if row is not None:
                written.append(row)
    return written


def authoring_update_unit(
    conn: Any,
    *,
    domain_key: str,
    kind: str,
    external_key: str,
    body: str,
    operator: str,
    tags: Optional[dict] = None,
    attrs: Optional[dict] = None,
) -> dict:
    """Update one existing unit; the unit must already exist.

    The event carries the full prior state as ``before`` and the written state
    as ``after``. Returns the stored KU dict.

    **整个函数在一个事务里**（理由见模块顶部的「事务」说明）。
    """
    domain = _load_domain(conn, domain_key=domain_key)
    with conn.transaction():
        prior = store.get_knowledge_unit(
            conn, kind=kind, external_key=external_key, namespace=domain["key"]
        )
        if prior is None:
            raise ValueError(
                f"unit {kind!r}/{external_key!r} not found in domain {domain_key!r}"
            )
        # The kernel decides create-vs-update from prior existence; the explicit
        # lookup above is what makes "update must exist" this surface's rule.
        from . import kernel_ports

        kernel = kernel_ports.kernel_for(conn, domain=domain)
        written = kernel.write(
            scope_id=domain["key"],
            kind=kind,
            external_key=external_key,
            body=body,
            actor=operator,
            via="authoring",
            tags=tags,
            attrs=attrs,
            tier="raw",
            provenance={"operator": operator},
            vocab_name="entity_types",
        )
    row = store.get_knowledge_unit(
        conn, kind=kind, external_key=written.unit.external_key, namespace=domain["key"]
    )
    return row if row is not None else written.unit  # pragma: no cover


def authoring_delete_unit(
    conn: Any, *, domain_key: str, kind: str, external_key: str, operator: str
) -> dict:
    """Soft-delete one existing unit (keeps the row, flags it deleted).

    Returns the updated KU dict (``tags["deleted"] is True``).
    """
    domain = _load_domain(conn, domain_key=domain_key)
    return _soft_delete_unit(
        conn, domain=domain, kind=kind, external_key=external_key, operator=operator
    )


def authoring_get_unit(
    conn: Any, *, domain_key: str, kind: str, external_key: str
) -> Optional[dict]:
    """Fetch one unit in the domain's namespace; ``None`` when missing.

    Soft-deleted units are returned as-is (``tags["deleted"]`` tells the
    caller); list views are the ones that filter them out.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    return store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=domain["key"]
    )


def authoring_list_units(
    conn: Any,
    *,
    domain_key: str,
    kind: Optional[str] = None,
    tier: Optional[str] = None,
    query: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 200,
) -> list[dict]:
    """List the domain's units, most recently updated first.

    Soft-deleted units are excluded unless ``include_deleted`` is set. The
    filtering happens in SQL rather than in Python so a ``limit`` means "the
    newest N matching units" — filtering after a LIMIT returned a short page
    that looked like an empty domain.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    return store.list_knowledge_units(
        conn,
        kind=kind,
        tier=tier,
        query=query,
        namespace=domain["key"],
        include_deleted=include_deleted,
        limit=limit,
    )


def authoring_live_entities(
    conn: Any, *, domain_key: str, limit: int = 1000
) -> list[dict]:
    """The domain's entity units that are not soft-deleted.

    This is the candidate list a relationship picker offers and the set a bulk
    import resolves its endpoints against — one function so the two cannot
    disagree about which entities "exist".
    """
    domain = _load_domain(conn, domain_key=domain_key)
    rows = store.list_knowledge_units(
        conn, namespace=domain["key"], include_deleted=False, limit=limit
    )
    entities = set(_vocabulary(conn, domain=domain, key="entity_types") or ())
    return [u for u in rows if u["kind"] in entities]


def authoring_fold_existing_keys(
    conn: Any,
    *,
    domain_key: str,
    dry_run: bool = True,
    limit: Optional[int] = None,
) -> dict:
    """把库里历史遗留的「未归名键」改成归名后的键（一次性对账，可 dry-run）。

    为什么需要它：写入口现在会归名，但归名之前写进去的行还留着原写法（实测
    2026-11-11 legal 有 1488 个这样的键：`中华人民共和国电信条例#第23条`、
    `中国银保监会…办法`）。键是身份，改它必须同时满足三件事，否则就是制造悬空：

    - **只改没有孪生的**：目标键已存在时不动（合并会丢掉一侧的 body/attrs，
      那是人的决定，不是脚本的决定）；
    - **原写法进 aliases**：合并/改名都要可解释；
    - **引用它的关系一起改**：关系的 external_key 与 attrs.from_key/to_key 都要
      重写，否则改名当场造出悬空关系。

    整批一个事务：任何一条失败就整体回滚，重跑幂等（第二次 0 变更）。
    """
    domain = _load_domain(conn, domain_key=domain_key)
    rules = keys.rules_for(domain["key"])
    if not rules:
        return {"domain": domain_key, "renamed": 0, "skipped_twin": 0,
                "reason": "该域未注册归名规则（不归名，安全默认）", "dry_run": dry_run,
                "plan": []}

    rows = conn.execute(
        "SELECT kind, external_key, attrs, body, tags FROM knowledge_units "
        "WHERE namespace = %s AND (tags->>'deleted') IS NULL",
        (domain["key"],),
    ).fetchall()
    live_pairs = {(r["kind"], r["external_key"]) for r in rows}
    plan: list[dict] = []
    for row in rows:
        folded, applied = keys.fold(row["external_key"], rules)
        folded = (folded or "").strip()
        if not folded or folded == row["external_key"]:
            continue
        if (row["kind"], folded) in live_pairs:
            plan.append({"kind": row["kind"], "old": row["external_key"],
                         "new": folded, "action": "skip_twin"})
            continue
        plan.append({"kind": row["kind"], "old": row["external_key"], "new": folded,
                     "action": "rename", "applied": list(applied)})

    renames = [p for p in plan if p["action"] == "rename"]
    twins = [p for p in plan if p["action"] == "skip_twin"]
    if limit:
        renames = renames[: int(limit)]
    if dry_run:
        return {"domain": domain_key, "renamed": len(renames), "skipped_twin": len(twins),
                "reason": None, "dry_run": True, "plan": renames[:20]}

    # 原地 UPDATE external_key：**不要 delete+insert**——行 id 是审计与血缘的锚，
    # 换 id 等于把同一个实体变成另一个实体。
    mapping = {p["old"]: p["new"] for p in renames}
    try:
        for p in renames:
            prior = store.get_knowledge_unit(
                conn, kind=p["kind"], external_key=p["old"], namespace=domain["key"])
            if prior is None:
                continue
            attrs = dict(prior.get("attrs") or {})
            aliases = set(attrs.get("aliases") or [])
            aliases.add(p["old"])
            attrs["aliases"] = sorted(aliases)
            attrs["folded_by"] = p["applied"]
            conn.execute(
                "UPDATE knowledge_units SET external_key = %s, attrs = %s::jsonb, "
                "updated_at = now() WHERE namespace = %s AND kind = %s AND external_key = %s",
                (p["new"], json.dumps(attrs, ensure_ascii=False), domain["key"],
                 p["kind"], p["old"]),
            )
            _record_event(
                conn, domain_id=domain["id"], unit_kind=p["kind"], unit_key=p["new"],
                op="update", before=_copy_unit(prior),
                after={**prior, "external_key": p["new"], "attrs": attrs},
                operator="fold-existing",
            )

        # 关系端点：键与 attrs 都要跟着改，否则改名当场造出悬空关系。
        rel_rows = conn.execute(
            "SELECT kind, external_key, body, attrs, tags, tier FROM knowledge_units "
            "WHERE namespace = %s AND (tags->>'deleted') IS NULL "
            "AND external_key LIKE '%%->%%'",
            (domain["key"],),
        ).fetchall()
        rewritten = 0
        for rel in rel_rows:
            frm, _, rest = (rel["external_key"] or "").partition("->")
            rkind, _, to = rest.partition(":")
            new_from, new_to = mapping.get(frm, frm), mapping.get(to, to)
            if new_from == frm and new_to == to:
                continue
            new_key = relationship_external_key(
                from_key=new_from, kind=rkind, to_key=new_to)
            attrs = dict(rel.get("attrs") or {})
            attrs["from_key"], attrs["to_key"] = new_from, new_to
            conn.execute(
                "UPDATE knowledge_units SET external_key = %s, attrs = %s::jsonb, "
                "updated_at = now() WHERE namespace = %s AND kind = %s AND external_key = %s",
                (new_key, json.dumps(attrs, ensure_ascii=False), domain["key"],
                 rel["kind"], rel["external_key"]),
            )
            _record_event(
                conn, domain_id=domain["id"], unit_kind=rel["kind"], unit_key=new_key,
                op="update",
                before={"external_key": rel["external_key"], "body": rel.get("body"),
                        "attrs": rel.get("attrs")},
                after={"external_key": new_key, "attrs": attrs},
                operator="fold-existing",
            )
            rewritten += 1
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return {"domain": domain_key, "renamed": len(renames), "skipped_twin": len(twins),
            "relations_rewritten": rewritten, "reason": None, "dry_run": False, "plan": []}


def authoring_live_keys(
    conn: Any,
    *,
    domain_key: str,
    kind: Optional[str] = None,
    prefix: Optional[str] = None,
) -> set[str]:
    """Every live unit key in the domain — optionally one kind, one key prefix.

    Deliberately *not* ``authoring_live_entities``: that one is capped at 1000
    rows because it feeds a picker, and reading it as "these exist" silently
    stops being true past the cap. Measured 2026-11-10: adopting a 1,208-article
    code read the first 1000 units, concluded the rest were missing every time,
    and rewrote the same 200 articles until the cap — the loop could never
    finish. A set membership question needs the whole set.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    sql = (
        "SELECT external_key FROM knowledge_units "
        "WHERE namespace = %s AND (tags->>'deleted') IS NULL"
    )
    params: list[Any] = [domain["key"]]
    if kind:
        sql += " AND kind = %s"
        params.append(kind)
    if prefix:
        sql += " AND external_key LIKE %s"
        params.append(prefix.replace("%", r"\%").replace("_", r"\_") + "%")
    return {r["external_key"] for r in conn.execute(sql, tuple(params)).fetchall()}


def authoring_live_key_kinds(conn: Any, *, domain_key: str) -> dict[str, str]:
    """``{external_key: kind}`` for every live unit — same reason as above.

    The extractor closes a relationship's endpoints against this map, so a capped
    version silently turns existing clauses into "missing endpoints": measured
    2026-11-10, the legal domain had 1,923 clause units and the first 1000 held no
    article of the code in question at all, so every grounding proposal was
    refused.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    rows = conn.execute(
        "SELECT external_key, kind FROM knowledge_units "
        "WHERE namespace = %s AND (tags->>'deleted') IS NULL",
        (domain["key"],),
    ).fetchall()
    return {r["external_key"]: r["kind"] for r in rows}


def authoring_unit_detail(
    conn: Any, *, domain_key: str, kind: str, external_key: str
) -> Optional[dict]:
    """One unit plus the relationships that touch it.

    A relationship stores its endpoints in ``attrs`` (``from_key``/``to_key``),
    so "what is this entity connected to" is a scan over the relationship units
    in the same namespace. Relations whose other end is soft-deleted are still
    returned with ``dangling=True`` — hiding them would make a deleted entity
    look unreferenced.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    unit = store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=domain["key"]
    )
    if unit is None:
        return None
    rel_kinds = set(_vocabulary(conn, domain=domain, key="relationship_kinds") or ())
    rels = [
        u
        for u in store.list_knowledge_units(conn, namespace=domain["key"], limit=2000)
        if u["kind"] in rel_kinds
        and external_key
        in (
            (u.get("attrs") or {}).get("from_key"),
            (u.get("attrs") or {}).get("to_key"),
        )
    ]
    live = {
        u["external_key"]
        for u in store.list_knowledge_units(
            conn, namespace=domain["key"], include_deleted=False, limit=2000
        )
    }
    related = []
    for rel in rels:
        attrs = rel.get("attrs") or {}
        other = attrs.get("to_key") if attrs.get("from_key") == external_key else attrs.get("from_key")
        related.append(
            {
                "kind": rel["kind"],
                "external_key": rel["external_key"],
                "from_key": attrs.get("from_key"),
                "to_key": attrs.get("to_key"),
                "other": other,
                "deleted": bool((rel.get("tags") or {}).get("deleted")),
                "dangling": other not in live,
            }
        )
    return {"unit": unit, "related": related,
            "deleted": bool((unit.get("tags") or {}).get("deleted"))}


# ------------------------------------------------------------------- events


def authoring_events_for(
    conn: Any,
    *,
    domain_id: int,
    unit_kind: Optional[str] = None,
    unit_key: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """The domain's change trail, newest first; filters are optional."""
    where, params = ["domain_id = %s"], [domain_id]
    if unit_kind is not None:
        where.append("unit_kind = %s")
        params.append(unit_kind)
    if unit_key is not None:
        where.append("unit_key = %s")
        params.append(unit_key)
    sql = (
        f"SELECT {_EVENT_COLS} FROM authoring_events "
        f"WHERE {' AND '.join(where)} ORDER BY created_at DESC, id DESC LIMIT %s"
    )
    params.append(limit)
    cur = conn.execute(sql, params)
    return [_event_to_dict(r) for r in cur.fetchall()]


# ------------------------------------------------------------ relationships


def relationship_external_key(*, from_key: str, kind: str, to_key: str) -> str:
    """Deterministic external key for a relationship unit.

    This key convention is a distribution-contract anchor: downstream
    publishing consumers derive relationship identity from it, so changing it
    breaks identity alignment with already-published data.
    """
    return RELATIONSHIP_KEY_TEMPLATE.format(from_key=from_key, kind=kind, to_key=to_key)


def authoring_create_relationship(
    conn: Any,
    *,
    domain_key: str,
    kind: str,
    from_key: str,
    to_key: str,
    body: str,
    operator: str,
    attrs: Optional[dict] = None,
) -> dict:
    """Create a relationship unit between two endpoint keys.

    The kind must be in the domain's ``relationship_kinds`` vocabulary (not
    ``entity_types``). The external key is derived via
    :func:`relationship_external_key`, and the structured endpoints are stored
    in ``attrs`` alongside any caller-supplied fields (the structural
    ``from``/``to`` values always win so identity cannot be corrupted through
    the payload). Returns the stored KU dict.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    # 端点先归名，再算关系键、再进 attrs。三处必须用**同一个**写法：
    # 只归键不归 attrs，就会出现"键是归名后的写法、attrs 里还是原文"这种自相矛盾
    # 的行（实测 2026-11-11 造出过一条，导致遗留键对账脚本误判为无需处理）。
    # 归名规则来自该域的 pack，没注册就什么都不折。
    from_key, _ = _fold_write_key(domain=domain, external_key=from_key, attrs=None)
    to_key, _ = _fold_write_key(domain=domain, external_key=to_key, attrs=None)
    external_key = relationship_external_key(from_key=from_key, kind=kind, to_key=to_key)
    merged_attrs = dict(attrs or {})
    merged_attrs.update(
        {"from": from_key, "to": to_key, "from_key": from_key, "to_key": to_key}
    )
    return _create_unit(
        conn,
        domain=domain,
        kind=kind,
        external_key=external_key,
        body=body,
        operator=operator,
        tags=None,
        attrs=merged_attrs,
        vocab_key="relationship_kinds",
    )


def authoring_delete_relationship(
    conn: Any,
    *,
    domain_key: str,
    kind: str,
    from_key: str,
    to_key: str,
    operator: str,
) -> dict:
    """Soft-delete a relationship unit by its endpoints. Returns the KU dict."""
    domain = _load_domain(conn, domain_key=domain_key)
    external_key = relationship_external_key(from_key=from_key, kind=kind, to_key=to_key)
    return _soft_delete_unit(
        conn, domain=domain, kind=kind, external_key=external_key, operator=operator
    )


# -------------------------------------------------------------------- tasks


def authoring_create_task(
    conn: Any,
    *,
    domain_id: int,
    assignee: str,
    title: str,
    detail: Optional[str],
    target_kind: Optional[str],
    target_key: Optional[str],
    created_by: str,
    assignee_kind: str = "human",
    assignee_ref: Optional[str] = None,
) -> dict:
    """Create one work task in status ``pending`` with the first trail entry.

    ``assignee`` stays the human-readable label; ``assignee_kind``/``assignee_ref``
    are what authorization reads. A ``fleet`` assignee must resolve to a live
    registration bound to this task's domain — the check lives here rather than
    at the route so no second call site can create an undeliverable task.
    """
    if not assignee or not title:
        raise ValueError("assignee and title are required")
    if assignee_kind not in ASSIGNEE_KINDS:
        raise ValueError(
            f"assignee_kind must be one of {list(ASSIGNEE_KINDS)}; got {assignee_kind!r}"
        )
    if assignee_kind == "fleet":
        if not (assignee_ref or "").strip():
            raise ValueError("assignee_kind='fleet' requires an assignee_ref")
        domain = conn.execute(
            "SELECT key FROM domains WHERE id = %s", (domain_id,)
        ).fetchone()
        if domain is None:
            raise ValueError(f"domain {domain_id} not found")
        from . import distribution

        _consumer, verdict = distribution.resolve_fleet(
            conn, fleet_ref=assignee_ref, domain_key=domain["key"]
        )
        if verdict != "ok":
            raise ValueError(
                f"assignee_ref {assignee_ref!r} 不是本域可用的舰队登记（{verdict}）"
            )
    elif assignee_kind == "kernel-role":
        ref = (assignee_ref or assignee or "").strip()
        if not ref:
            raise ValueError("assignee_kind='kernel-role' requires a role name")
        assignee_ref = ref

    entry = {"from": None, "to": "pending", "by": created_by, "at": _now()}
    cur = conn.execute(
        f"INSERT INTO authoring_tasks "
        f"(domain_id, assignee, title, detail, target_kind, target_key, "
        f"status, transitions, created_by, assignee_kind, assignee_ref) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        f"RETURNING {_TASK_COLS}",
        (
            domain_id,
            assignee,
            title,
            detail,
            target_kind,
            target_key,
            "pending",
            json.dumps([entry]),
            created_by,
            assignee_kind,
            assignee_ref,
        ),
    )
    task = _task_to_dict(cur.fetchone())
    conn.commit()
    return task


def authoring_list_tasks(
    conn: Any,
    *,
    domain_id: int,
    assignee: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    """List the domain's tasks, newest first; filters are optional."""
    where, params = ["domain_id = %s"], [domain_id]
    if assignee is not None:
        where.append("assignee = %s")
        params.append(assignee)
    if status is not None:
        where.append("status = %s")
        params.append(status)
    cur = conn.execute(
        f"SELECT {_TASK_COLS} FROM authoring_tasks "
        f"WHERE {' AND '.join(where)} ORDER BY created_at DESC, id DESC",
        params,
    )
    return [_task_to_dict(r) for r in cur.fetchall()]


def authoring_get_task(conn: Any, *, task_id: int) -> Optional[dict]:
    """Fetch one task; ``None`` when missing."""
    cur = conn.execute(
        f"SELECT {_TASK_COLS} FROM authoring_tasks WHERE id = %s", (task_id,)
    )
    row = cur.fetchone()
    return _task_to_dict(row) if row else None


def authoring_transition_task(
    conn: Any, *, task_id: int, to_status: str, actor: str
) -> dict:
    """Move a task to ``to_status`` and append the trail entry.

    One statement updates ``status``, ``updated_at`` and appends the
    ``transitions`` entry (``{"from", "to", "by", "at"}``), so the trail can
    never diverge from the status. Unknown task or unknown status is refused.
    """
    if to_status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {list(TASK_STATUSES)}")
    current = authoring_get_task(conn, task_id=task_id)
    if current is None:
        raise ValueError(f"task {task_id} not found")
    moment = _now()
    entry = {"from": current["status"], "to": to_status, "by": actor, "at": moment}
    cur = conn.execute(
        f"UPDATE authoring_tasks SET status = %s, updated_at = %s, "
        f"transitions = transitions || %s::jsonb "
        f"WHERE id = %s RETURNING {_TASK_COLS}",
        (to_status, moment, json.dumps([entry]), task_id),
    )
    task = _task_to_dict(cur.fetchone())
    conn.commit()
    return task


class TaskAlreadyClaimed(ValueError):
    """Another executor won the claim. Distinct from "task not found".

    The two need different handling at the edge: "not found" is a bad id; "already
    claimed" means someone else is doing it, so the caller should pick another
    order instead of retrying this one.
    """


def authoring_claim_task(conn: Any, *, task_id: int, actor: str) -> dict:
    """Claim a ``pending`` task for ``actor`` (``pending`` → ``in_progress``).

    **Exclusive by construction**: the guard is the ``WHERE status = 'pending'``
    on the UPDATE itself, and the affected-row count decides the winner. Reading
    the status first and then updating would let two executors both read
    ``pending`` and both succeed.

    A ``done``/``cancelled`` task cannot be claimed (nothing left to do), and a
    task already ``in_progress`` belongs to whoever claimed it first.
    """
    moment = _now()
    entry = {"from": "pending", "to": "in_progress", "by": actor, "at": moment}
    cur = conn.execute(
        f"UPDATE authoring_tasks SET status = 'in_progress', updated_at = %s, "
        f"transitions = transitions || %s::jsonb "
        f"WHERE id = %s AND status = 'pending' RETURNING {_TASK_COLS}",
        (moment, json.dumps([entry]), task_id),
    )
    row = cur.fetchone()
    if row is None:
        current = authoring_get_task(conn, task_id=task_id)
        if current is None:
            raise ValueError(f"task {task_id} not found")
        raise TaskAlreadyClaimed(
            f"task {task_id} 已被认领（当前状态 {current['status']}）"
        )
    task = _task_to_dict(row)
    conn.commit()
    return task


def authoring_complete_task(
    conn: Any,
    *,
    task_id: int,
    actor: str,
    artifact_refs: Optional[list] = None,
    note: Optional[str] = None,
) -> dict:
    """Close an ``in_progress`` task (``in_progress`` → ``done``).

    ``pending`` may **not** jump straight to ``done``: an order nobody claimed has
    no executor to attribute the result to, and the ledger would then show work
    that nobody did.

    Completion records artifacts and a note **in the trail entry**, not in a
    second table: the task row stays the single place that answers "what happened
    to this order", and ``transitions`` is append-only by construction.
    Completing MUST NOT write knowledge units — content still goes through the
    proposal path or the kernel write path.
    """
    moment = _now()
    entry: dict[str, Any] = {"from": "in_progress", "to": "done", "by": actor, "at": moment}
    if artifact_refs:
        entry["artifacts"] = list(artifact_refs)
    if note:
        entry["note"] = note
    cur = conn.execute(
        f"UPDATE authoring_tasks SET status = 'done', updated_at = %s, "
        f"transitions = transitions || %s::jsonb "
        f"WHERE id = %s AND status = 'in_progress' RETURNING {_TASK_COLS}",
        (moment, json.dumps(entry), task_id),
    )
    row = cur.fetchone()
    if row is None:
        current = authoring_get_task(conn, task_id=task_id)
        if current is None:
            raise ValueError(f"task {task_id} not found")
        raise ValueError(
            f"task {task_id} 必须先认领才能完成（当前状态 {current['status']}）"
        )
    task = _task_to_dict(row)
    conn.commit()
    return task
