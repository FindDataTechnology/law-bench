"""Expert authoring kernel surface (add-expert-authoring-surface, tasks 3.1-3.4).

Covers the kernel-level semantics of ``src/bench/authoring.py`` (no HTTP):

- 词表执法 (3.1): in-vocab creates land as raw-tier KUs in the domain
  namespace with operator provenance and a create event; out-of-vocab kinds
  are refused naming the allowed vocabulary and produce zero KUs and zero
  events; relationship kinds are gated against ``relationship_kinds`` (not
  ``entity_types``) and vice versa; unknown domain keys fail closed on every
  entry point.
- 域隔离写作 (3.2): content physically lives under the authoring domain's
  namespace only — invisible to another domain's list and get.
- 变更事件流 (3.3): create/update/delete events carry full before/after
  states; the trail is ordered; delete is soft (flag, not row removal);
  event insert and KU write share one transaction (event failure rolls the
  whole write back, connection stays usable); create-on-existing-key logs
  op='update' (D6 prior-existence rule).
- 任务 (3.4, kernel half): tasks start pending with the first trail entry,
  every transition appends {from,to,by,at}, invalid status/unknown task are
  refused, cancelled works, and list filters by assignee and status.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.bench import authoring, templates, workspaces
from src.bench.store import get_knowledge_unit
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so DDL lands on the per-test DB
    # instead of the process-wide cached shared connection (which stays bound
    # to whichever test DB connected first).
    ensure_schema(db_path=empty_db)
    yield empty_db


def authoring_schema() -> dict:
    """Template schema aligned with the kernel vocabularies; the authoring
    gate reads entity_types / relationship_kinds from exactly this data."""
    return {
        "entity_types": ["company", "indicator"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }


def make_domain(conn, key: str) -> dict:
    """One template + one member domain instantiated from it; return the domain."""
    tmpl = templates.create_template(
        conn, name=f"tpl-{key}", schema=authoring_schema(), created_by="admin-1"
    )
    return workspaces.instantiate_domain(
        conn,
        key=key,
        name=f"Domain {key}",
        template_name=f"tpl-{key}",
        template_version=tmpl["version"],
        created_by="admin-1",
    )


def make_two_domains(conn, key_a: str, key_b: str) -> tuple[dict, dict]:
    """Two domains sharing one template (unique domain keys, same vocab)."""
    templates.create_template(
        conn, name=f"tpl-{key_a}", schema=authoring_schema(), created_by="admin-1"
    )
    a = workspaces.instantiate_domain(
        conn, key=key_a, name=f"Domain {key_a}",
        template_name=f"tpl-{key_a}", template_version=None, created_by="admin-1",
    )
    b = workspaces.instantiate_domain(
        conn, key=key_b, name=f"Domain {key_b}",
        template_name=f"tpl-{key_a}", template_version=None, created_by="admin-1",
    )
    return a, b


def ku_count(conn, namespace: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_units WHERE namespace = %s",
        (namespace,),
    ).fetchone()
    return row["n"]


def event_count(conn, domain_id: int, op: str | None = None) -> int:
    if op is None:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM authoring_events WHERE domain_id = %s",
            (domain_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM authoring_events "
            "WHERE domain_id = %s AND op = %s",
            (domain_id, op),
        ).fetchone()
    return row["n"]


def create_company(conn, domain_key: str, external_key: str = "co-1", body: str = "某公司条目") -> dict:
    return authoring.authoring_create_unit(
        conn,
        domain_key=domain_key,
        kind="company",
        external_key=external_key,
        body=body,
        operator="expert-1",
        tags={"theme": "market"},
        attrs={"hq": "北京"},
    )


# ---------------------------------------------------------------- 词表执法


def test_in_vocab_create_lands_raw_with_provenance_and_create_event(db_conn):
    """词表内创作成功: KU 以该域 namespace 落库, tier 初始为 raw, 操作者进入溯源."""
    domain = make_domain(db_conn, "dom-vocab-in")

    written = create_company(db_conn, "dom-vocab-in", external_key="co-1")

    assert written["kind"] == "company"
    assert written["namespace"] == "dom-vocab-in"  # domain key is the namespace
    assert written["external_key"] == "co-1"
    assert written["tier"] == "raw"
    assert written["body"] == "某公司条目"
    assert written["provenance"] == {"operator": "expert-1", "via": "authoring"}

    # the raw row agrees (physical evidence, not just the returned dict)
    row = db_conn.execute(
        "SELECT namespace, tier, provenance FROM knowledge_units "
        "WHERE kind = %s AND external_key = %s",
        ("company", "co-1"),
    ).fetchone()
    assert row["namespace"] == "dom-vocab-in"
    assert row["tier"] == "raw"
    assert row["provenance"]["operator"] == "expert-1"
    assert row["provenance"]["via"] == "authoring"

    # a create event was recorded
    events = authoring.authoring_events_for(db_conn, domain_id=domain["id"])
    assert len(events) == 1
    ev = events[0]
    assert ev["op"] == "create"
    assert ev["unit_kind"] == "company"
    assert ev["unit_key"] == "co-1"
    assert ev["operator"] == "expert-1"
    assert ev["via"] == "authoring"


def test_out_of_vocab_kind_rejected_naming_vocab_writes_nothing(db_conn):
    """出表 kind 拒绝: 报明该域允许的词表, 不产生任何 KU 或事件."""
    domain = make_domain(db_conn, "dom-vocab-out")

    with pytest.raises(ValueError) as exc:
        authoring.authoring_create_unit(
            db_conn,
            domain_key="dom-vocab-out",
            kind="merger",  # not in entity_types ["company", "indicator"]
            external_key="co-x",
            body="出表实体",
            operator="expert-1",
        )
    message = str(exc.value)
    assert "allowed kinds" in message
    assert "'company'" in message
    assert "'indicator'" in message

    # 不产生任何 KU 或事件
    assert ku_count(db_conn, "dom-vocab-out") == 0
    assert event_count(db_conn, domain["id"]) == 0


def test_relationship_kind_gated_against_relationship_kinds_vocab(db_conn):
    """Relationship kinds are gated against relationship_kinds, NOT entity_types
    — each gate rejects the other vocabulary's kind."""
    domain = make_domain(db_conn, "dom-vocab-rel")

    # entity-kind gate rejects a relationship kind: "belongs_to" is not in
    # entity_types, and the refusal names that (entity_types) vocabulary
    with pytest.raises(ValueError, match="entity_types"):
        authoring.authoring_create_unit(
            db_conn,
            domain_key="dom-vocab-rel",
            kind="belongs_to",
            external_key="r-x",
            body="关系当实体提交",
            operator="expert-1",
        )
    # vice versa: relationship gate rejects an entity kind
    with pytest.raises(ValueError, match="relationship_kinds"):
        authoring.authoring_create_relationship(
            db_conn,
            domain_key="dom-vocab-rel",
            kind="company",
            from_key="co-1",
            to_key="co-2",
            body="实体当关系提交",
            operator="expert-1",
        )
    assert ku_count(db_conn, "dom-vocab-rel") == 0
    assert event_count(db_conn, domain["id"]) == 0

    # positive control: an in-vocab relationship lands with the deterministic
    # external key and structured endpoints (the gate uses the right vocab)
    rel = authoring.authoring_create_relationship(
        db_conn,
        domain_key="dom-vocab-rel",
        kind="belongs_to",
        from_key="co-1",
        to_key="co-2",
        body="隶属关系",
        operator="expert-1",
    )
    assert rel["external_key"] == "co-1->belongs_to:co-2"
    assert rel["namespace"] == "dom-vocab-rel"
    assert rel["tier"] == "raw"
    assert rel["attrs"]["from"] == "co-1"
    assert rel["attrs"]["to"] == "co-2"
    assert rel["provenance"] == {"operator": "expert-1", "via": "authoring"}
    events = authoring.authoring_events_for(db_conn, domain_id=domain["id"])
    assert [e["op"] for e in events] == ["create"]
    assert events[0]["unit_key"] == "co-1->belongs_to:co-2"


def test_unknown_domain_key_raises_on_every_entry_point(db_conn):
    """Fail-closed isolation: unknown domain key refuses all read/write paths."""
    make_domain(db_conn, "dom-real")
    ghost = "dom-ghost"

    with pytest.raises(ValueError, match="domain 'dom-ghost' not found"):
        authoring.authoring_create_unit(
            db_conn, domain_key=ghost, kind="company", external_key="k",
            body="b", operator="expert-1",
        )
    with pytest.raises(ValueError, match="not found"):
        authoring.authoring_update_unit(
            db_conn, domain_key=ghost, kind="company", external_key="k",
            body="b", operator="expert-1",
        )
    with pytest.raises(ValueError, match="not found"):
        authoring.authoring_delete_unit(
            db_conn, domain_key=ghost, kind="company", external_key="k",
            operator="expert-1",
        )
    with pytest.raises(ValueError, match="not found"):
        authoring.authoring_list_units(db_conn, domain_key=ghost)
    with pytest.raises(ValueError, match="not found"):
        authoring.authoring_get_unit(db_conn, domain_key=ghost, kind="company", external_key="k")

    # nothing was written under the ghost namespace and the real domain is untouched
    assert ku_count(db_conn, ghost) == 0
    assert ku_count(db_conn, "dom-real") == 0


# ---------------------------------------------------------------- 域隔离写作


def test_isolation_content_lives_only_in_authoring_domain_namespace(db_conn):
    """隔离写作: 内容仅存在于 A 域 namespace 下; B 域的请求中不出现该内容."""
    dom_a, dom_b = make_two_domains(db_conn, "dom-iso-a", "dom-iso-b")
    create_company(db_conn, "dom-iso-a", external_key="co-iso")

    # B domain sees nothing, via list AND via get
    assert authoring.authoring_list_units(db_conn, domain_key="dom-iso-b") == []
    assert authoring.authoring_get_unit(
        db_conn, domain_key="dom-iso-b", kind="company", external_key="co-iso"
    ) is None

    # A domain still sees its own content
    listed = authoring.authoring_list_units(db_conn, domain_key="dom-iso-a")
    assert [u["external_key"] for u in listed] == ["co-iso"]

    # physical evidence: the only namespace in the table is A's key
    namespaces = {
        r["namespace"]
        for r in db_conn.execute("SELECT DISTINCT namespace FROM knowledge_units").fetchall()
    }
    assert namespaces == {"dom-iso-a"}
    assert ku_count(db_conn, "dom-iso-b") == 0


# ---------------------------------------------------------------- 变更事件流


def test_create_event_before_none_after_carries_written_unit(db_conn):
    domain = make_domain(db_conn, "dom-ev-create")
    written = create_company(db_conn, "dom-ev-create")

    events = authoring.authoring_events_for(db_conn, domain_id=domain["id"])
    assert len(events) == 1
    ev = events[0]
    assert ev["op"] == "create"
    assert ev["before"] is None
    # after carries the written unit exactly (body/tags/attrs/identity)
    assert ev["after"] == written
    assert ev["after"]["body"] == "某公司条目"
    assert ev["after"]["tags"] == {"theme": "market"}
    assert ev["after"]["attrs"] == {"hq": "北京"}
    assert ev["after"]["namespace"] == "dom-ev-create"


def test_update_event_carries_full_before_and_ordered_trail(db_conn):
    """变更留痕: before/after 携带完整前后状态与操作者; 原内容历史不受影响."""
    domain = make_domain(db_conn, "dom-ev-update")
    first = create_company(db_conn, "dom-ev-update", external_key="co-u")
    prior = get_knowledge_unit(
        db_conn, kind="company", external_key="co-u", namespace="dom-ev-update"
    )
    assert prior == first

    updated = authoring.authoring_update_unit(
        db_conn,
        domain_key="dom-ev-update",
        kind="company",
        external_key="co-u",
        body="更新后的条目",
        operator="expert-2",
        tags={"theme": "revised"},
        attrs={"hq": "上海"},
    )
    assert updated["body"] == "更新后的条目"
    assert updated["provenance"]["operator"] == "expert-2"

    events = authoring.authoring_events_for(db_conn, domain_id=domain["id"])
    assert [e["op"] for e in events] == ["update", "create"]  # newest first
    upd = events[0]
    assert upd["operator"] == "expert-2"
    # before carries the FULL prior unit dict
    assert upd["before"] == prior
    assert upd["before"]["body"] == "某公司条目"
    assert upd["before"]["tags"] == {"theme": "market"}
    assert upd["before"]["attrs"] == {"hq": "北京"}
    assert upd["before"]["kind"] == "company"
    assert upd["before"]["external_key"] == "co-u"
    assert upd["before"]["namespace"] == "dom-ev-update"
    # after is the new state
    assert upd["after"] == updated

    # the older create event is untouched by the update (原内容历史不受影响)
    assert events[1]["after"]["body"] == "某公司条目"
    assert events[1]["after"]["tags"] == {"theme": "market"}

    # filters narrow the trail to the unit
    keyed = authoring.authoring_events_for(
        db_conn, domain_id=domain["id"], unit_kind="company", unit_key="co-u"
    )
    assert [e["op"] for e in keyed] == ["update", "create"]


def test_delete_is_soft_and_event_records_prior_state(db_conn):
    domain = make_domain(db_conn, "dom-ev-delete")
    create_company(db_conn, "dom-ev-delete", external_key="co-d")

    deleted = authoring.authoring_delete_unit(
        db_conn,
        domain_key="dom-ev-delete",
        kind="company",
        external_key="co-d",
        operator="expert-2",
    )
    assert deleted["tags"]["deleted"] is True
    assert deleted["body"] == "某公司条目"  # content preserved unchanged

    # the row still exists physically, flagged deleted
    raw = get_knowledge_unit(
        db_conn, kind="company", external_key="co-d", namespace="dom-ev-delete"
    )
    assert raw is not None
    assert raw["tags"]["deleted"] is True

    # excluded from the default list view, visible with include_deleted
    assert authoring.authoring_list_units(db_conn, domain_key="dom-ev-delete") == []
    with_deleted = authoring.authoring_list_units(
        db_conn, domain_key="dom-ev-delete", include_deleted=True
    )
    assert [u["external_key"] for u in with_deleted] == ["co-d"]
    assert with_deleted[0]["tags"]["deleted"] is True

    # delete event: op='delete', before=prior unit, after=None
    events = authoring.authoring_events_for(db_conn, domain_id=domain["id"])
    assert [e["op"] for e in events] == ["delete", "create"]
    dele = events[0]
    assert dele["operator"] == "expert-2"
    assert dele["before"] is not None
    assert dele["before"]["body"] == "某公司条目"
    assert "deleted" not in (dele["before"]["tags"] or {})  # prior was NOT yet flagged
    assert dele["after"] is None


def _atomicity_case(db_conn, path: str, key: str):
    """Shared body of the same-transaction tests: run the failing write, return
    nothing; asserts live in the callers via the returned prior state."""
    if path == "create":
        authoring.authoring_create_unit(
            db_conn, domain_key="dom-atomic", kind="company", external_key=key,
            body="v2-attempt", operator="expert-2",
        )
    elif path == "update":
        authoring.authoring_update_unit(
            db_conn, domain_key="dom-atomic", kind="company", external_key=key,
            body="v2-attempt", operator="expert-2",
        )
    else:
        authoring.authoring_delete_unit(
            db_conn, domain_key="dom-atomic", kind="company", external_key=key,
            operator="expert-2",
        )


@pytest.mark.parametrize("path", ["create", "update", "delete"])
def test_event_failure_rolls_back_whole_write_and_connection_stays_usable(
    db_conn, monkeypatch, path
):
    """同事务 (spec: 事件失败则整个写入失败): when the event insert fails, the
    paired KU write must not survive, and the connection must stay usable."""
    domain = make_domain(db_conn, "dom-atomic")
    key = f"co-{path}"
    prior = None
    if path in ("update", "delete"):
        prior = create_company(db_conn, "dom-atomic", external_key=key)

    def _boom(*args, **kwargs):
        raise RuntimeError("event insert exploded")

    with monkeypatch.context() as m:  # patch restored on context exit
        m.setattr(authoring, "_record_event", _boom)
        with pytest.raises(RuntimeError, match="event insert exploded"):
            _atomicity_case(db_conn, path, key)

    # 同事务: the KU write did NOT survive the event failure
    unit = get_knowledge_unit(
        db_conn, kind="company", external_key=key, namespace="dom-atomic"
    )
    if path == "create":
        assert unit is None  # nothing was committed
        assert ku_count(db_conn, "dom-atomic") == 0
        assert event_count(db_conn, domain["id"]) == 0
    elif path == "update":
        assert unit == prior  # prior state intact, v2-attempt never landed
        assert event_count(db_conn, domain["id"], "update") == 0
        assert event_count(db_conn, domain["id"]) == 1  # only the prior create
    else:
        assert unit == prior  # NOT flagged deleted
        assert "deleted" not in unit["tags"]
        assert event_count(db_conn, domain["id"], "delete") == 0
        assert event_count(db_conn, domain["id"]) == 1  # only the prior create

    # the connection remains usable for a subsequent successful write
    if path == "create":
        # the rolled-back insert left no conflicting row: the same key creates cleanly
        healed = authoring.authoring_create_unit(
            db_conn, domain_key="dom-atomic", kind="company", external_key=key,
            body="v3-after-heal", operator="expert-3",
        )
        assert healed["body"] == "v3-after-heal"
        assert event_count(db_conn, domain["id"], "create") == 1
    else:
        healed = authoring.authoring_update_unit(
            db_conn, domain_key="dom-atomic", kind="company", external_key=key,
            body="v3-after-heal", operator="expert-3",
        )
        assert healed["body"] == "v3-after-heal"
        assert event_count(db_conn, domain["id"], "update") == 1
    assert get_knowledge_unit(
        db_conn, kind="company", external_key=key, namespace="dom-atomic"
    )["body"] == "v3-after-heal"


def test_event_sql_failure_check_violation_rolls_back_write(db_conn, monkeypatch):
    """同事务, genuine SQL failure flavor: force the event INSERT itself to
    violate its op CHECK constraint — the failure happens inside the driver,
    so this proves the event insert and the KU write really share one
    transaction and that the aborted transaction is rolled back cleanly."""
    from psycopg.errors import CheckViolation

    domain = make_domain(db_conn, "dom-atomic-sql")
    real_record = authoring._record_event

    def _bad_op(conn, **kwargs):
        return real_record(conn, **{**kwargs, "op": "not-an-op"})

    with monkeypatch.context() as m:
        m.setattr(authoring, "_record_event", _bad_op)
        with pytest.raises(CheckViolation):
            authoring.authoring_create_unit(
                db_conn, domain_key="dom-atomic-sql", kind="company",
                external_key="co-sql", body="v2-attempt", operator="expert-2",
            )

    assert ku_count(db_conn, "dom-atomic-sql") == 0
    assert event_count(db_conn, domain["id"]) == 0

    # connection recovered: a normal create lands afterwards
    healed = create_company(db_conn, "dom-atomic-sql", external_key="co-sql", body="v3")
    assert healed["body"] == "v3"
    assert event_count(db_conn, domain["id"], "create") == 1


def test_create_on_existing_key_logs_update_event(db_conn):
    """D6 prior-existence rule: authoring_create_unit over an existing key
    logs op='update' with the full prior state as before."""
    domain = make_domain(db_conn, "dom-ev-d6")
    first = create_company(db_conn, "dom-ev-d6", external_key="co-d6", body="第一版")

    second = authoring.authoring_create_unit(
        db_conn,
        domain_key="dom-ev-d6",
        kind="company",
        external_key="co-d6",
        body="第二版",
        operator="expert-2",
        tags={"theme": "again"},
        attrs={"hq": "深圳"},
    )
    assert second["body"] == "第二版"

    # still exactly one KU row (upsert identity, no duplicate)
    assert ku_count(db_conn, "dom-ev-d6") == 1

    events = authoring.authoring_events_for(db_conn, domain_id=domain["id"])
    assert [e["op"] for e in events] == ["update", "create"]  # newest first
    upd = events[0]
    assert upd["op"] == "update"
    assert upd["operator"] == "expert-2"
    assert upd["before"] == first  # full prior unit, not None
    assert upd["before"]["body"] == "第一版"
    assert upd["after"] == second


# ---------------------------------------------------------------- 任务 (3.4 kernel half)


def test_create_task_starts_pending_with_first_trail_entry(db_conn):
    domain = make_domain(db_conn, "dom-task-create")
    task = authoring.authoring_create_task(
        db_conn,
        domain_id=domain["id"],
        assignee="expert-1",
        title="起草 company 实体",
        detail="补全公司条目描述",
        target_kind="company",
        target_key="co-1",
        created_by="lead-1",
    )
    assert task["domain_id"] == domain["id"]
    assert task["assignee"] == "expert-1"
    assert task["title"] == "起草 company 实体"
    assert task["detail"] == "补全公司条目描述"
    assert task["target_kind"] == "company"
    assert task["target_key"] == "co-1"
    assert task["created_by"] == "lead-1"
    assert task["status"] == "pending"

    # the first trail entry: from None to pending, by the creator, timestamped
    assert len(task["transitions"]) == 1
    entry = task["transitions"][0]
    assert entry["from"] is None
    assert entry["to"] == "pending"
    assert entry["by"] == "lead-1"
    assert entry["at"]
    datetime.fromisoformat(entry["at"])  # parses as an ISO timestamp

    # fetch agrees with what create returned
    fetched = authoring.authoring_get_task(db_conn, task_id=task["id"])
    assert fetched["status"] == "pending"
    assert fetched["transitions"] == task["transitions"]


def test_transition_chain_appends_each_trail_step(db_conn):
    """指派到完成: 领取 (in_progress) 并完成后置 done, 状态流转全程留痕."""
    domain = make_domain(db_conn, "dom-task-chain")
    task = authoring.authoring_create_task(
        db_conn, domain_id=domain["id"], assignee="expert-1", title="条目核验",
        detail=None, target_kind="indicator", target_key="ind-1",
        created_by="lead-1",
    )
    created_at = datetime.fromisoformat(task["created_at"])

    moved = authoring.authoring_transition_task(
        db_conn, task_id=task["id"], to_status="in_progress", actor="expert-1"
    )
    assert moved["status"] == "in_progress"
    moved = authoring.authoring_transition_task(
        db_conn, task_id=task["id"], to_status="done", actor="expert-1"
    )
    assert moved["status"] == "done"

    transitions = moved["transitions"]
    assert [(t["from"], t["to"]) for t in transitions] == [
        (None, "pending"),
        ("pending", "in_progress"),
        ("in_progress", "done"),
    ]
    # who did what: creator made the implicit first entry, the expert the rest
    assert [t["by"] for t in transitions] == ["lead-1", "expert-1", "expert-1"]
    for t in transitions:
        datetime.fromisoformat(t["at"])

    # updated_at moved forward with the transitions
    assert datetime.fromisoformat(moved["updated_at"]) >= created_at

    # the persisted row agrees with the returned dict
    fetched = authoring.authoring_get_task(db_conn, task_id=task["id"])
    assert fetched["status"] == "done"
    assert fetched["transitions"] == transitions


def test_transition_refuses_invalid_status_and_unknown_task(db_conn):
    domain = make_domain(db_conn, "dom-task-bad")
    task = authoring.authoring_create_task(
        db_conn, domain_id=domain["id"], assignee="expert-1", title="t",
        detail=None, target_kind=None, target_key=None, created_by="lead-1",
    )
    with pytest.raises(ValueError, match="status must be one of"):
        authoring.authoring_transition_task(
            db_conn, task_id=task["id"], to_status="archived", actor="expert-1"
        )
    # the refused transition left no trail and did not move the status
    fetched = authoring.authoring_get_task(db_conn, task_id=task["id"])
    assert fetched["status"] == "pending"
    assert len(fetched["transitions"]) == 1

    with pytest.raises(ValueError, match="not found"):
        authoring.authoring_transition_task(
            db_conn, task_id=999999, to_status="done", actor="expert-1"
        )


def test_transition_to_cancelled_works(db_conn):
    domain = make_domain(db_conn, "dom-task-cancel")
    task = authoring.authoring_create_task(
        db_conn, domain_id=domain["id"], assignee="expert-1", title="取消我",
        detail=None, target_kind=None, target_key=None, created_by="lead-1",
    )
    moved = authoring.authoring_transition_task(
        db_conn, task_id=task["id"], to_status="cancelled", actor="lead-1"
    )
    assert moved["status"] == "cancelled"
    assert [(t["from"], t["to"], t["by"]) for t in moved["transitions"]] == [
        (None, "pending", "lead-1"),
        ("pending", "cancelled", "lead-1"),
    ]


def test_list_tasks_filters_by_assignee_and_status(db_conn):
    domain = make_domain(db_conn, "dom-task-list")
    mk = lambda assignee, title: authoring.authoring_create_task(
        db_conn, domain_id=domain["id"], assignee=assignee, title=title,
        detail=None, target_kind=None, target_key=None, created_by="lead-1",
    )
    t1 = mk("alice", "t1")
    t2 = mk("bob", "t2")
    t3 = mk("alice", "t3")
    authoring.authoring_transition_task(
        db_conn, task_id=t3["id"], to_status="in_progress", actor="alice"
    )

    # unfiltered: all of the domain's tasks, newest first
    ids = [t["id"] for t in authoring.authoring_list_tasks(db_conn, domain_id=domain["id"])]
    assert ids == [t3["id"], t2["id"], t1["id"]]

    # by assignee only
    alice = authoring.authoring_list_tasks(db_conn, domain_id=domain["id"], assignee="alice")
    assert [t["id"] for t in alice] == [t3["id"], t1["id"]]

    # assignee + status together
    pending = authoring.authoring_list_tasks(
        db_conn, domain_id=domain["id"], assignee="alice", status="pending"
    )
    assert [t["id"] for t in pending] == [t1["id"]]

    # status only
    in_progress = authoring.authoring_list_tasks(
        db_conn, domain_id=domain["id"], status="in_progress"
    )
    assert [t["id"] for t in in_progress] == [t3["id"]]

    # a non-matching assignee sees nothing
    assert authoring.authoring_list_tasks(db_conn, domain_id=domain["id"], assignee="nobody") == []


def _password_from_database_url() -> str | None:
    """The password from ``database_url`` (the conninfo from a live conn drops it)."""
    import os
    from urllib.parse import urlsplit

    dsn = os.environ.get("database_url") or os.environ.get("DATABASE_URL") or ""
    if not dsn:
        return None
    try:
        return urlsplit(dsn).password
    except ValueError:
        return None


def test_event_failure_rolls_back_on_the_production_autocommit_conn(empty_db, monkeypatch):
    """事件写入失败时 KU 必须一起回滚——**用 autocommit 连接测**。

    审计 03 §2/§8：生产共享连接是 `psycopg.connect(..., autocommit=True)`
    （为了长 LLM 调用不长挂事务）。psycopg 3 在 autocommit 连接上
    `commit()`/`rollback()` 是 **no-op**（`transaction_status` 永远 IDLE）。

    **为什么这条测试必须自己开 autocommit 连接**：`db_conn` fixture 用的
    `empty_db` 是默认非 autocommit 连接，在那种连接上 `rollback()` 本来就有效，
    旧代码照样能回滚——用它测会得到一条**永远绿的假测试**（我第一版就写错了，
    反向实验时发现旧代码也通过）。只有 autocommit 连接才能复现生产行为。

    断言：异常传出 + `knowledge_units` 里没有这条 unit。
    """
    import psycopg
    from psycopg.rows import dict_row

    # `conn.info.dsn` is libpq's conninfo, which **never carries the password** —
    # locally that is masked by trust auth / .pgpass, on CI the reconnect fails
    # with `fe_sendauth: no password supplied`. Carry it explicitly from the
    # configured URL (the per-test DB only changes the dbname).
    dsn = empty_db.info.dsn
    password = _password_from_database_url()
    conn = psycopg.connect(
        dsn, row_factory=dict_row, autocommit=True,
        **({"password": password} if password else {}),
    )
    try:
        ensure_schema(conn)
        make_domain(conn, "dom-atomic")

        def boom(*a, **kw):
            raise RuntimeError("事件写入失败")

        monkeypatch.setattr(authoring, "_record_event", boom)

        with pytest.raises(RuntimeError):
            create_company(conn, "dom-atomic", external_key="co-rollback")

        row = conn.execute(
            "SELECT 1 FROM knowledge_units WHERE kind = %s AND external_key = %s",
            ("company", "co-rollback"),
        ).fetchone()
        assert row is None, (
            "autocommit 连接上，事件写入失败后 KU 仍然落库了 —— 内容表与审计轨迹分叉。"
            "说明写路径没有真正的事务边界（autocommit 下 commit()/rollback() 是 no-op）"
        )
    finally:
        conn.close()
