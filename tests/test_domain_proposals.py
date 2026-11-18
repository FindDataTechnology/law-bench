"""Domain proposal inbox (src/bench/proposals.py).

Runs against ``empty_db`` + ``ensure_schema`` (the full kernel schema), the
same fixture style as ``tests/test_authoring_kernel.py``. Covers the workflow
rules that make the inbox auditable: evidence is mandatory and digested,
submission is idempotent per key, rejection needs a reason and only new
evidence can reopen a rejected key, self-confirmation is banned, confirmation
writes through the one kernel path exactly once, and a domain key can never
reach another domain's inbox.
"""

from __future__ import annotations

import pytest

from src.bench import proposals, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so DDL lands on the per-test DB
    # instead of the process-wide cached shared connection.
    ensure_schema(db_path=empty_db)
    yield empty_db

def authoring_schema() -> dict:
    """Template schema aligned with the kernel vocabularies."""
    return {
        "entity_types": ["company", "indicator"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }


def make_domain(conn, key: str) -> dict:
    """One template + one domain instantiated from it; return the domain.

    Also provisions the fleet/agent sources these tests submit with — after
    add-fleet-execution-loop a ``fleet:`` source must resolve to a live
    registration (see tests/_fleet_fixtures.py).
    """
    tmpl = templates.create_template(
        conn, name=f"tpl-{key}", schema=authoring_schema(), created_by="admin-1"
    )
    domain = workspaces.instantiate_domain(
        conn,
        key=key,
        name=f"Domain {key}",
        template_name=f"tpl-{key}",
        template_version=tmpl["version"],
        created_by="admin-1",
    )
    from _fleet_fixtures import provision_default_fleet_world

    provision_default_fleet_world(conn, domains=[key])
    return domain


def make_two_domains(conn, key_a: str, key_b: str) -> tuple[dict, dict]:
    """Two domains sharing one template (distinct domain keys, same vocab)."""
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
    from _fleet_fixtures import provision_default_fleet_world

    provision_default_fleet_world(conn, domains=[key_a, key_b])
    return a, b


_DEFAULT_EVIDENCE = object()


def submit_company(conn, domain_key: str, *, external_key: str = "co-1",
                   evidence=_DEFAULT_EVIDENCE, submitted_by: str = "expert-1") -> dict:
    # A sentinel, not None: "no evidence" (None) is itself a case under test.
    if evidence is _DEFAULT_EVIDENCE:
        evidence = {"citation": "年报 p.12"}
    return proposals.submit(
        conn,
        domain_key=domain_key,
        source="fleet:a/1",
        kind="company",
        external_key=external_key,
        body="某公司条目",
        evidence=evidence,
        impact="补齐主体档案",
        submitted_by=submitted_by,
    )


def ku_count(conn, namespace: str, kind: str | None = None) -> int:
    if kind is None:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM knowledge_units WHERE namespace = %s",
            (namespace,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM knowledge_units "
            "WHERE namespace = %s AND kind = %s",
            (namespace, kind),
        ).fetchone()
    return row["n"]


def authoring_event_count(conn, domain_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM authoring_events WHERE domain_id = %s",
        (domain_id,),
    ).fetchone()
    return row["n"]


def proposal_event_count(conn, proposal_id: int, to_state: str | None = None) -> int:
    if to_state is None:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM domain_proposal_events WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM domain_proposal_events "
            "WHERE proposal_id = %s AND to_state = %s",
            (proposal_id, to_state),
        ).fetchone()
    return row["n"]


# --------------------------------------------------------------- 举证必须


@pytest.mark.parametrize("bad_evidence", [None, "", "   ", {}, []])
def test_submit_requires_evidence(db_conn, bad_evidence):
    """None / empty string / whitespace / empty dict / empty list are all
    "nothing behind the claim": refused before any row is written."""
    make_domain(db_conn, "dom-evidence")
    with pytest.raises(ValueError, match="提案必须携带依据"):
        submit_company(db_conn, "dom-evidence", evidence=bad_evidence)

    assert proposals.count_pending(db_conn, domain_key="dom-evidence") == 0
    assert proposals.list_proposals(db_conn, domain_key="dom-evidence") == []


@pytest.mark.parametrize(
    "field,value", [("kind", ""), ("external_key", " "), ("body", "")]
)
def test_submit_requires_text_fields(db_conn, field, value):
    """kind / external_key / body must be non-empty strings."""
    make_domain(db_conn, "dom-text")
    kwargs = dict(
        domain_key="dom-text",
        source="fleet:a/1",
        kind="company",
        external_key="co-1",
        body="某公司条目",
        evidence={"citation": "年报 p.12"},
        submitted_by="expert-1",
    )
    kwargs[field] = value
    with pytest.raises(ValueError, match=field):
        proposals.submit(db_conn, **kwargs)
    assert proposals.count_pending(db_conn, domain_key="dom-text") == 0


def test_digest_is_stable_across_key_order(db_conn):
    """Canonical JSON: dict ordering never changes the digest."""
    first = proposals.canonical_evidence_digest({"a": 1, "b": [2, 3]})
    second = proposals.canonical_evidence_digest({"b": [2, 3], "a": 1})
    assert first == second
    assert len(first) == 64


# ------------------------------------------------------------- 幂等提交


def test_submit_is_idempotent_per_pending_key(db_conn):
    """3x same (domain, source, external_key) -> one pending row, same id,
    and the first evidence snapshot is returned unchanged."""
    make_domain(db_conn, "dom-idem")

    first = submit_company(db_conn, "dom-idem", evidence={"citation": "first"})
    second = submit_company(db_conn, "dom-idem", evidence={"citation": "second"})
    third = submit_company(db_conn, "dom-idem", evidence={"citation": "third"})

    assert first["id"] == second["id"] == third["id"]
    assert third["state"] == "pending"
    assert third["evidence"] == {"citation": "first"}  # not overwritten
    assert third["evidence_digest"] == first["evidence_digest"]
    assert proposals.count_pending(db_conn, domain_key="dom-idem") == 1
    assert len(proposals.list_proposals(db_conn, domain_key="dom-idem")) == 1
    # only the actual insert appended an event
    assert proposal_event_count(db_conn, first["id"]) == 1


# ------------------------------------------------------------- 驳回规则


def test_reject_requires_a_note(db_conn):
    """A bare rejection is not actionable: the reason is mandatory."""
    make_domain(db_conn, "dom-reject-note")
    proposal = submit_company(db_conn, "dom-reject-note")

    for bad in ("", "   "):
        with pytest.raises(ValueError, match="驳回必须写明理由"):
            proposals.reject(
                db_conn,
                domain_key="dom-reject-note",
                proposal_id=proposal["id"],
                actor="lead-1",
                note=bad,
            )
    assert proposals.get(
        db_conn, domain_key="dom-reject-note", proposal_id=proposal["id"]
    )["state"] == "pending"


def test_reject_then_resubmit_needs_new_evidence(db_conn):
    """Same evidence after rejection -> refused; different evidence -> a new
    pending row (the rejected row stays on record)."""
    make_domain(db_conn, "dom-resubmit")
    evidence = {"citation": "旧年报 p.12"}
    first = submit_company(db_conn, "dom-resubmit", evidence=evidence)
    rejected = proposals.reject(
        db_conn,
        domain_key="dom-resubmit",
        proposal_id=first["id"],
        actor="lead-1",
        note="依据过期",
    )
    assert rejected["state"] == "rejected"
    assert rejected["decided_by"] == "lead-1"
    assert rejected["decision_note"] == "依据过期"

    # rejecting twice is idempotent (no second event)
    again = proposals.reject(
        db_conn,
        domain_key="dom-resubmit",
        proposal_id=first["id"],
        actor="lead-1",
        note="依据过期",
    )
    assert again["id"] == first["id"]
    assert proposal_event_count(db_conn, first["id"], "rejected") == 1

    with pytest.raises(ValueError, match="同键已驳回"):
        submit_company(db_conn, "dom-resubmit", evidence=evidence)

    second = submit_company(
        db_conn, "dom-resubmit", evidence={"citation": "新年报 p.3"}
    )
    assert second["id"] != first["id"]
    assert second["state"] == "pending"
    assert second["evidence"] == {"citation": "新年报 p.3"}
    assert proposals.count_pending(db_conn, domain_key="dom-resubmit") == 1
    assert len(
        proposals.list_proposals(db_conn, domain_key="dom-resubmit")
    ) == 2


# ----------------------------------------------------------- 自提自确认


def test_self_confirm_is_banned_and_admin_override_allows_it(db_conn):
    """The submitter cannot approve their own proposal; an explicit admin
    override can, and the override is stamped into the decision note."""
    domain = make_domain(db_conn, "dom-self")
    proposal = submit_company(db_conn, "dom-self", submitted_by="expert-1")

    with pytest.raises(PermissionError, match="提案人不得自提自确认"):
        proposals.confirm(
            db_conn,
            domain_key="dom-self",
            proposal_id=proposal["id"],
            actor="expert-1",
        )
    assert proposals.get(
        db_conn, domain_key="dom-self", proposal_id=proposal["id"]
    )["state"] == "pending"
    assert ku_count(db_conn, "dom-self") == 0

    confirmed = proposals.confirm(
        db_conn,
        domain_key="dom-self",
        proposal_id=proposal["id"],
        actor="expert-1",
        admin_override=True,
    )
    assert confirmed["state"] == "confirmed"
    assert confirmed["decided_by"] == "expert-1"
    assert confirmed["decision_note"].startswith("[admin-override]")
    assert ku_count(db_conn, "dom-self", "company") == 1
    assert authoring_event_count(db_conn, domain["id"]) == 1


def test_admin_confirming_someone_elses_proposal_writes_no_override_tag(db_conn):
    """The override tag marks a waiver that actually happened.

    An admin confirming a proposal submitted by *another* identity never met the
    separation-of-duties rule, so stamping "[admin-override]" there would claim a
    waiver in the audit trail that did not occur. The note must stay empty.
    """
    make_domain(db_conn, "dom-other-author")
    proposal = submit_company(db_conn, "dom-other-author", submitted_by="expert-1")

    confirmed = proposals.confirm(
        db_conn,
        domain_key="dom-other-author",
        proposal_id=proposal["id"],
        actor="dev@local",
        admin_override=True,
    )
    assert confirmed["state"] == "confirmed"
    assert confirmed["decision_note"] == ""
    events = proposals.events_for(db_conn, proposal_id=proposal["id"])
    # The event column stores NULL for "no note" (the proposal row stores '');
    # either way nothing may claim an override happened.
    assert not events[-1]["note"]


# ------------------------------------------------- 确认走内核唯一写路径


def test_confirm_writes_one_ku_through_the_kernel_and_one_event(db_conn):
    """Confirmation produces a real KU with operator provenance and exactly
    one 'confirmed' transition; confirming again is a no-op."""
    domain = make_domain(db_conn, "dom-confirm")
    proposal = submit_company(db_conn, "dom-confirm", submitted_by="expert-1")

    confirmed = proposals.confirm(
        db_conn, domain_key="dom-confirm", proposal_id=proposal["id"], actor="lead-1"
    )
    assert confirmed["state"] == "confirmed"
    assert confirmed["decided_by"] == "lead-1"
    assert confirmed["decision_note"] == ""

    unit = db_conn.execute(
        "SELECT kind, namespace, external_key, body, tier, provenance "
        "FROM knowledge_units WHERE namespace = %s",
        ("dom-confirm",),
    ).fetchone()
    assert unit["kind"] == "company"
    assert unit["external_key"] == "co-1"
    assert unit["body"] == "某公司条目"
    assert unit["tier"] == "raw"
    assert unit["provenance"] == {"operator": "lead-1", "via": "authoring"}

    # the kernel wrote its own append-only event
    assert authoring_event_count(db_conn, domain["id"]) == 1

    events = proposals.events_for(db_conn, proposal_id=proposal["id"])
    assert [e["to_state"] for e in events] == ["pending", "confirmed"]
    assert events[1]["actor"] == "lead-1"
    assert events[1]["from_state"] == "pending"

    # idempotent second confirm: no second KU, no second event
    second = proposals.confirm(
        db_conn, domain_key="dom-confirm", proposal_id=proposal["id"], actor="lead-1"
    )
    assert second["id"] == proposal["id"]
    assert second["state"] == "confirmed"
    assert ku_count(db_conn, "dom-confirm") == 1
    assert proposal_event_count(db_conn, proposal["id"], "confirmed") == 1
    assert proposals.count_pending(db_conn, domain_key="dom-confirm") == 0


def test_confirm_relationship_uses_the_relationship_kernel_path(db_conn):
    """A relationship-kind proposal lands as a relationship KU with the
    kernel's deterministic key (endpoints read from the evidence payload).

    端点先入库是提交前的硬前提（refuse-unlandable-proposals）：提案箱不替关系
    造端点，所以「两端都在」必须在提交那一刻就成立。这条用例的意图仍只关于
    确认走哪条内核路径——前置补上，判据不变。
    """
    domain = make_domain(db_conn, "dom-rel")
    _seed_unit(db_conn, "dom-rel", key="co-1")
    _seed_unit(db_conn, "dom-rel", key="grp-1")
    proposal = proposals.submit(
        db_conn,
        domain_key="dom-rel",
        source="fleet:a/1",
        kind="belongs_to",
        external_key="co-1->belongs_to:grp-1",
        body="归属关系",
        evidence={"from_key": "co-1", "to_key": "grp-1", "citation": "公告"},
        submitted_by="expert-1",
    )

    proposals.confirm(
        db_conn, domain_key="dom-rel", proposal_id=proposal["id"], actor="lead-1"
    )

    row = db_conn.execute(
        "SELECT kind, external_key, attrs FROM knowledge_units "
        "WHERE namespace = %s AND kind = 'belongs_to'",
        ("dom-rel",),
    ).fetchone()
    assert row["kind"] == "belongs_to"
    assert row["external_key"] == "co-1->belongs_to:grp-1"
    assert row["attrs"]["from_key"] == "co-1"
    assert row["attrs"]["to_key"] == "grp-1"
    assert authoring_event_count(db_conn, domain["id"]) == 3  # 两条端点 + 这条关系


# --------------------------------------------------------------- 词表外


def test_confirm_out_of_vocabulary_kind_writes_nothing(db_conn):
    """A kind in neither vocabulary is refused naming both lists and the
    anchored template version, before any KU or transition is written."""
    domain = make_domain(db_conn, "dom-oov")
    proposal = submit_company(db_conn, "dom-oov", external_key="co-x")
    # Move the proposal to an unvetted kind through the inbox (submission is
    # permissive; only confirmation gates the vocabulary).
    db_conn.execute(
        "UPDATE domain_proposals SET kind = 'gadget' WHERE id = %s",
        (proposal["id"],),
    )
    db_conn.commit()

    with pytest.raises(ValueError) as exc:
        proposals.confirm(
            db_conn, domain_key="dom-oov", proposal_id=proposal["id"], actor="lead-1"
        )
    message = str(exc.value)
    assert "不在模板 v1 词表内" in message
    assert "entity_types" in message and "relationship_kinds" in message
    assert "'company'" in message
    assert "'belongs_to'" in message

    assert ku_count(db_conn, "dom-oov") == 0
    assert authoring_event_count(db_conn, domain["id"]) == 0
    assert proposals.get(
        db_conn, domain_key="dom-oov", proposal_id=proposal["id"]
    )["state"] == "pending"
    assert proposal_event_count(db_conn, proposal["id"]) == 1  # submit only


# --------------------------------------------------------------- 跨域隔离


def test_cross_domain_proposal_is_invisible_and_undecidable(db_conn):
    """Domain B's key can neither read nor decide a proposal that lives in A,
    and an unknown domain key fails closed."""
    make_two_domains(db_conn, "dom-a", "dom-b")
    proposal = submit_company(db_conn, "dom-a")

    assert proposals.get(
        db_conn, domain_key="dom-b", proposal_id=proposal["id"]
    ) is None
    assert proposals.list_proposals(db_conn, domain_key="dom-b") == []
    assert proposals.count_pending(db_conn, domain_key="dom-b") == 0

    with pytest.raises(ValueError, match="not found in domain 'dom-b'"):
        proposals.confirm(
            db_conn, domain_key="dom-b", proposal_id=proposal["id"], actor="lead-1"
        )
    with pytest.raises(ValueError, match="not found in domain 'dom-b'"):
        proposals.reject(
            db_conn,
            domain_key="dom-b",
            proposal_id=proposal["id"],
            actor="lead-1",
            note="不属于本域",
        )

    # a domain key that does not exist is refused on the read side too
    with pytest.raises(ValueError, match="domain 'dom-missing' not found"):
        proposals.get(db_conn, domain_key="dom-missing", proposal_id=proposal["id"])

    # A's own key still sees it, untouched
    assert proposals.get(
        db_conn, domain_key="dom-a", proposal_id=proposal["id"]
    )["state"] == "pending"


def test_the_same_claim_from_two_producers_is_one_row(db_conn):
    """去重按**主张**，不是按提交方。

    实测风险：幂等身份过去是 (domain, source, external_key)，舰队岗与应用内岗位
    同时提出同一条主张会变成两行待确认——人眼只有一双。
    """
    make_domain(db_conn, "legal")
    # `kind` 在这里只是标签，但必须落在夹具模板的词表内（company/indicator）：
    # 词表外的 proposal 现在在提交口就被拒，而那样一条提案本来就永远确认不了。
    first = proposals.submit(
        db_conn, domain_key="legal", source="fleet:a/1", kind="indicator",
        external_key="indicator-y", body="b", evidence={"quote": "q"},
        submitted_by="fleet:a/1")
    again = proposals.submit(
        db_conn, domain_key="legal", source="agent:concept@legal", kind="indicator",
        external_key="indicator-y", body="b", evidence={"quote": "q"},
        submitted_by="agent:concept@legal")

    assert again["id"] == first["id"], "同键同依据只有一行"
    assert set(again["sources"]) == {"fleet:a/1", "agent:concept@legal"}
    n = db_conn.execute("SELECT COUNT(*) AS n FROM domain_proposals").fetchone()["n"]
    assert n == 1


def test_different_evidence_for_the_same_key_stays_two_rows(db_conn):
    """证据不同不能合并：分歧本身是信息，交给人判。"""
    make_domain(db_conn, "legal")
    proposals.submit(db_conn, domain_key="legal", source="fleet:a/1", kind="indicator",
                     external_key="indicator-x", body="b",
                     evidence={"quote": "第一种说法"}, submitted_by="fleet:a/1")
    proposals.submit(db_conn, domain_key="legal", source="fleet:b/2", kind="indicator",
                     external_key="indicator-x", body="b",
                     evidence={"quote": "第二种说法"}, submitted_by="fleet:b/2")
    rows = db_conn.execute(
        "SELECT external_key, sources FROM domain_proposals WHERE state='pending'").fetchall()
    assert len(rows) == 2
    assert all(r["sources"] for r in rows), "每行都要记自己的提交方"


# ------------------------------------- 机器身份不得当确认人（不止 agent:）


def test_a_fleet_identity_cannot_sign_a_confirmation(db_conn):
    """2026-11-14 生产实历的回归钉子。

    原来的闸只判 `is_agent(actor)`（只认 `agent:` 前缀），于是我在产库上用
    `actor="fleet:probe"` 调了一次 `confirm`——它**通过了**：提案被确认、内核写出单元、
    审计里留下 `operator="fleet:probe"`。规则的本意是「确认是人类 lead 的职责」，
    按名字前缀只挡一类机器身份，等于把「谁是机器」交给调用方拼字符串。
    """
    domain = make_domain(db_conn, "dom-machine-sign")
    _ = domain
    proposal = submit_company(
        db_conn, "dom-machine-sign",
        submitted_by="fleet:fleet_1794335712751_wfa3ww/post_x",
    )

    for actor in ("fleet:probe", "fleet:fleet_1794335712751_wfa3ww/post_x"):
        with pytest.raises(PermissionError, match="机器身份不得确认提案"):
            proposals.confirm(
                db_conn,
                domain_key="dom-machine-sign",
                proposal_id=proposal["id"],
                actor=actor,
            )

    # 拒绝必须发生在写之前：状态不变、内核没被调用
    assert proposals.get(
        db_conn, domain_key="dom-machine-sign", proposal_id=proposal["id"]
    )["state"] == "pending"
    assert ku_count(db_conn, "dom-machine-sign") == 0

    # 人（lead）照常能确认同一张提案
    confirmed = proposals.confirm(
        db_conn,
        domain_key="dom-machine-sign",
        proposal_id=proposal["id"],
        actor="lead-1",
    )
    assert confirmed["state"] == "confirmed"
    assert confirmed["decided_by"] == "lead-1"
    assert ku_count(db_conn, "dom-machine-sign") == 1


# ─────────────────────────────────────────────────────────── 提交前预检（预检 ≠ 判决）
# 背景（2026-11-15 生产实测）：legal 域 41 条被驳回的提案里，8 条是「键已在库」、
# 4 条是「关系端点不闭合」。这两类与内容无关，只看域里此刻有什么，机器判得了。
# 留给人判的代价不是「多看一眼」，而是确认一步走的是单位 upsert ⇒ 确认一条重复键
# 提案会**改写**既有单位的正文，而提交方在提交那一刻读不到这件事。


def _seed_unit(conn, domain_key: str, *, kind: str = "company", key: str = "co-live",
               body: str = "既有条目正文") -> dict:
    from src.bench import authoring

    return authoring.authoring_create_unit(
        conn, domain_key=domain_key, kind=kind, external_key=key,
        body=body, operator="expert-0",
    )


def test_duplicate_live_key_is_refused_at_submit_not_at_review(db_conn):
    """重复键拒在提交口：不入箱、不占确认位、既有单位正文一字不动。"""
    make_domain(db_conn, "dom-dup")
    unit = _seed_unit(db_conn, "dom-dup", key="co-live", body="既有条目正文")
    before = proposals.submit.__module__  # noqa: F841 - 保持 import 形状可读

    with pytest.raises(proposals.ProposalTargetExists) as caught:
        submit_company(db_conn, "dom-dup", external_key="co-live")

    assert caught.value.reason == "key_already_live"
    assert str(unit["id"]) in caught.value.detail
    assert caught.value.hint  # 处置方向必须写得出来，否则等于只说「不行」
    assert proposals.count_pending(db_conn, domain_key="dom-dup") == 0
    from src.bench import authoring

    after = authoring.authoring_get_unit(
        db_conn, domain_key="dom-dup", kind="company", external_key="co-live"
    )
    assert after["body"] == "既有条目正文"


def test_relationship_with_missing_endpoint_is_refused(db_conn):
    """关系端点未入库：确认时必失败，所以拒在提交口，并点名缺哪个。"""
    make_domain(db_conn, "dom-rel")
    _seed_unit(db_conn, "dom-rel", key="co-left")

    with pytest.raises(proposals.ProposalTargetExists) as caught:
        proposals.submit(
            db_conn, domain_key="dom-rel", source="fleet:a/1", kind="belongs_to",
            external_key="co-left->belongs_to:co-ghost", body="左属于右",
            evidence={"from_key": "co-left", "to_key": "co-ghost"}, submitted_by="expert-1",
        )

    assert caught.value.reason == "endpoints_missing"
    assert "co-ghost" in caught.value.detail
    assert proposals.count_pending(db_conn, domain_key="dom-rel") == 0


def test_relationship_with_both_endpoints_live_is_accepted(db_conn):
    """成对的正路：两端都在，关系提案照常进箱——预检不能宽到把正路也拦掉。"""
    make_domain(db_conn, "dom-rel-ok")
    _seed_unit(db_conn, "dom-rel-ok", key="co-left")
    _seed_unit(db_conn, "dom-rel-ok", key="co-right")

    proposal = proposals.submit(
        db_conn, domain_key="dom-rel-ok", source="fleet:a/1", kind="belongs_to",
        external_key="co-left->belongs_to:co-right", body="左属于右",
        evidence={"from_key": "co-left", "to_key": "co-right"}, submitted_by="expert-1",
    )
    assert proposal["state"] == "pending"


def test_same_key_under_another_kind_is_refused_naming_the_live_kind(db_conn):
    """同键异 kind：那会造出同一键的两条单位，正是键归名一直在防的分叉。"""
    make_domain(db_conn, "dom-xkind")
    _seed_unit(db_conn, "dom-xkind", kind="company", key="dup-1")

    with pytest.raises(proposals.ProposalTargetExists) as caught:
        proposals.submit(
            db_conn, domain_key="dom-xkind", source="fleet:a/1", kind="indicator",
            external_key="dup-1", body="同一个键换个 kind",
            evidence={"citation": "台账 p.3"}, submitted_by="expert-1",
        )

    assert caught.value.reason == "key_already_live"
    assert "kind=company" in caught.value.detail


def test_idempotent_replay_stays_created_false_despite_preflight(db_conn):
    """预检排在去重之后：重放仍返回既有提案与 created=false。

    这条是顺序纪律的钉子——预检若跑到去重前面，第一份提案进箱后的合法重放
    就会变成 409，把「新增 vs 幂等命中」这个报数基石打穿。
    """
    make_domain(db_conn, "dom-replay")
    first, created_first = proposals.submit(
        db_conn, domain_key="dom-replay", source="fleet:a/1", kind="company",
        external_key="co-replay", body="条目", evidence={"citation": "x"},
        submitted_by="expert-1", with_created=True,
    )
    assert created_first is True

    second, created_second = proposals.submit(
        db_conn, domain_key="dom-replay", source="fleet:a/1", kind="company",
        external_key="co-replay", body="条目", evidence={"citation": "x"},
        submitted_by="expert-1", with_created=True,
    )
    assert created_second is False
    assert second["id"] == first["id"]


def test_preflight_does_not_touch_semantic_judgements(db_conn):
    """文种名/角色名这类「值不值得入库」是人的裁决，预检不越位。"""
    make_domain(db_conn, "dom-semantic")
    proposal = proposals.submit(
        db_conn, domain_key="dom-semantic", source="fleet:a/1", kind="company",
        external_key="关于XX的通知", body="文种名，不可跨文复用",
        evidence={"citation": "标题"}, submitted_by="expert-1",
    )
    assert proposal["state"] == "pending"


def test_relationship_closed_by_a_pending_endpoint_is_accepted(db_conn):
    """同批闭合：端点还没入库、但已在箱里 ⇒ 关系提案照常进箱。

    进程内抽取流水线就是这么工作的（实体与关系同一批提交）。第一版预检只认活单位，
    把这条主路当场拒掉（`test_ontology_extraction.py::test_same_batch_entity_closes_the_endpoint`
    的 submitted 从 3 掉到 2）。「正在闭合」与「压根没有」必须分开。
    """
    make_domain(db_conn, "dom-batch")
    for key in ("co-batch", "co-batch2"):
        proposals.submit(
            db_conn, domain_key="dom-batch", source="fleet:a/1", kind="company",
            external_key=key, body="同批端点",
            evidence={"citation": "同批"}, submitted_by="expert-1",
        )
    relation = proposals.submit(
        db_conn, domain_key="dom-batch", source="fleet:a/1", kind="belongs_to",
        external_key="co-batch->belongs_to:co-batch2", body="同批关系",
        evidence={"from_key": "co-batch", "to_key": "co-batch2"}, submitted_by="expert-1",
    )
    assert relation["state"] == "pending"


# ------------------------------------------------- 第三类：词表外的 kind
#
# 前两类（键已在库、端点未闭合）判的是「目标域此刻有什么」；这一类判的是
# 「这个域的模板认不认这个 kind」——它同样是确定性的：确认走 `_write_through_kernel`
# → `_lane_for_kind`，同一张词表在那里抛 ValueError，所以这条提案永远确认不了。
# 生产实证（2026-11-16 只读）：legal 域 14 条 pending 里 3 条 `kind='n:1'`，
# source 全是 `fleet:`——直连提交方才是这一类的人群（抽取侧提交前已按同一张
# 模板词表预筛，见 extraction.py 的 bad_kind）。


def test_kind_outside_template_vocabulary_is_refused_at_submit(db_conn):
    """词表外的 kind 拒在提交口：不入箱，并点名模板版本与两张词表。"""
    make_domain(db_conn, "dom-vocab")

    with pytest.raises(proposals.ProposalTargetExists) as caught:
        proposals.submit(
            db_conn, domain_key="dom-vocab", source="fleet:a/1", kind="n:1",
            external_key="co-a->n:1:co-b", body="探针草稿里的基数写法",
            evidence={"from_key": "co-a", "to_key": "co-b"}, submitted_by="expert-1",
        )

    assert caught.value.reason == "kind_not_in_vocabulary"
    # 判词必须印出当事的事实：kind、模板版本、两张词表各一个都不许少，
    # 否则提交方只会去猜「到底是哪一个字写错了」。
    assert "n:1" in caught.value.detail
    assert "v1" in caught.value.detail
    assert "company" in caught.value.detail and "belongs_to" in caught.value.detail
    assert caught.value.hint
    assert proposals.count_pending(db_conn, domain_key="dom-vocab") == 0


def test_kind_inside_vocabulary_still_enters_the_inbox(db_conn):
    """成对的正路：词表内的 kind 照常进箱——拦的必须是词表，不是「所有提交」。"""
    make_domain(db_conn, "dom-vocab-ok")
    proposal = proposals.submit(
        db_conn, domain_key="dom-vocab-ok", source="fleet:a/1", kind="indicator",
        external_key="ind-1", body="词表内的 kind",
        evidence={"citation": "台账 p.7"}, submitted_by="expert-1",
    )
    assert proposal["state"] == "pending"


