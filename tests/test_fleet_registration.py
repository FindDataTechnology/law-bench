"""Fleet registration + submitter resolution (add-fleet-execution-loop §2.1/§2.2b).

两个面在这里被钉住：

1. **登记**：舰队登记必须带稳定的 ``fleet_ref``，机器登记必须不带；同一 ``fleet_ref``
   至多一条未吊销登记——吊销后可以重新登记，历史行保留。
2. **解析**：``resolve_submitter`` 只负责把登记行与成员事实取来，判断交给
   ``submitters.verdict``；它必须对三类来源给出与纯函数一致的结论。这条测试的存在
   理由就是防止有人在这里另写一套判断（那会让纯函数那 36 条测试保护的不是线上行为）。
"""

from __future__ import annotations

import pytest

from src.bench import distribution, submitters, workspaces


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    yield empty_db


def _domain(conn, key="legal"):
    from src.bench import templates
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS

    schema = {
        "entity_types": ["company", "indicator"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    tmpl = templates.create_template(
        conn, name=f"tpl-{key}", schema=schema, created_by="tester"
    )
    return workspaces.instantiate_domain(
        conn,
        key=key,
        name=key.upper(),
        template_name=f"tpl-{key}",
        template_version=tmpl["version"],
        created_by="tester",
    )


# --------------------------------------------------------------- registration


def test_fleet_registration_carries_ref(db_conn):
    c = distribution.register_consumer(
        db_conn, name="ontology-fleet-win", domains=["legal"], token_hash="h1",
        created_by="admin", kind="fleet", fleet_ref="fleet_1794335712751_wfa3ww",
    )
    assert c["kind"] == "fleet"
    assert c["fleet_ref"] == "fleet_1794335712751_wfa3ww"


def test_machine_registration_projects_machine_kind(db_conn):
    c = distribution.register_consumer(
        db_conn, name="fd-wire", domains=["legal"], token_hash="h2", created_by="admin",
    )
    assert c["kind"] == "machine" and c["fleet_ref"] is None


def test_fleet_without_ref_is_refused(db_conn):
    with pytest.raises(ValueError, match="fleet_ref"):
        distribution.register_consumer(
            db_conn, name="f", domains=["legal"], token_hash="h3",
            created_by="admin", kind="fleet",
        )


def test_machine_with_ref_is_refused(db_conn):
    """A machine consumer claiming a fleet identity is a contradiction."""
    with pytest.raises(ValueError, match="must not carry"):
        distribution.register_consumer(
            db_conn, name="m", domains=["legal"], token_hash="h4",
            created_by="admin", kind="machine", fleet_ref="fleet_x",
        )


def test_unknown_kind_is_refused(db_conn):
    with pytest.raises(ValueError, match="kind must be one of"):
        distribution.register_consumer(
            db_conn, name="k", domains=["legal"], token_hash="h5",
            created_by="admin", kind="robot",
        )


def test_one_live_registration_per_fleet(db_conn):
    distribution.register_consumer(
        db_conn, name="first", domains=["legal"], token_hash="h6",
        created_by="admin", kind="fleet", fleet_ref="fleet_1",
    )
    with pytest.raises(ValueError, match="already registered as 'first'"):
        distribution.register_consumer(
            db_conn, name="second", domains=["legal"], token_hash="h7",
            created_by="admin", kind="fleet", fleet_ref="fleet_1",
        )


def test_revoked_registration_frees_the_fleet_ref(db_conn):
    distribution.register_consumer(
        db_conn, name="first", domains=["legal"], token_hash="h8",
        created_by="admin", kind="fleet", fleet_ref="fleet_1",
    )
    distribution.revoke_consumer(db_conn, name="first")
    again = distribution.register_consumer(
        db_conn, name="second", domains=["legal"], token_hash="h9",
        created_by="admin", kind="fleet", fleet_ref="fleet_1",
    )
    assert again["name"] == "second" and again["revoked_at"] is None


# ------------------------------------------------- promote (machine → fleet)


def test_promotion_locates_by_credential_and_changes_only_two_columns(db_conn):
    """凭据本身就是授权：按 token 定位，只改 kind / fleet_ref。"""
    before = distribution.register_consumer(
        db_conn, name="ontology-fleet-win", domains=["legal"], token_hash="h-promote",
        created_by="admin",
    )
    after = distribution.promote_consumer_to_fleet(
        db_conn, token_hash="h-promote", fleet_ref="fleet_win",
    )
    assert (after["kind"], after["fleet_ref"]) == ("fleet", "fleet_win")
    assert (after["id"], after["name"], after["token_hash"], after["domains"]) == (
        before["id"], before["name"], "h-promote", ["legal"],
    )


def test_promotion_refuses_when_the_given_name_is_not_the_credential_owner(db_conn):
    distribution.register_consumer(
        db_conn, name="owner", domains=["legal"], token_hash="h-owner", created_by="admin",
    )
    with pytest.raises(ValueError, match="凭据与提供的 token 不一致"):
        distribution.promote_consumer_to_fleet(
            db_conn, name="owner", token_hash="h-other", fleet_ref="fleet_x",
        )
    assert distribution.list_consumers(db_conn)[0]["kind"] == "machine"


def test_promotion_needs_something_to_locate_by(db_conn):
    with pytest.raises(ValueError, match="需要 name 或 token_hash"):
        distribution.promote_consumer_to_fleet(db_conn, fleet_ref="fleet_x")
    with pytest.raises(ValueError, match="找不到要升级的登记"):
        distribution.promote_consumer_to_fleet(
            db_conn, name="nobody", token_hash="h-none", fleet_ref="fleet_x",
        )


# ------------------------------------------------------------ resolve_fleet


def test_resolve_fleet_ok_and_verdicts(db_conn):
    _domain(db_conn)
    _, v = distribution.resolve_fleet(db_conn, fleet_ref="nope", domain_key="legal")
    assert v == "unregistered"

    distribution.register_consumer(
        db_conn, name="f1", domains=["gov"], token_hash="h10",
        created_by="admin", kind="fleet", fleet_ref="fleet_gov",
    )
    consumer, v = distribution.resolve_fleet(db_conn, fleet_ref="fleet_gov", domain_key="legal")
    assert consumer is not None and v == "domain_mismatch"

    distribution.set_consumer_domains(db_conn, name="f1", domains=["legal"])
    _, v = distribution.resolve_fleet(db_conn, fleet_ref="fleet_gov", domain_key="legal")
    assert v == "ok"

    distribution.revoke_consumer(db_conn, name="f1")
    _, v = distribution.resolve_fleet(db_conn, fleet_ref="fleet_gov", domain_key="legal")
    assert v == "revoked"


# -------------------------------------------------------- resolve_submitter


def test_resolve_submitter_fleet_paths(db_conn):
    _domain(db_conn)
    distribution.register_consumer(
        db_conn, name="f1", domains=["legal"], token_hash="h11",
        created_by="admin", kind="fleet", fleet_ref="fleet_abc",
    )

    consumer, v = distribution.resolve_submitter(
        db_conn, source="fleet:fleet_abc/m_1", domain_key="legal", via=submitters.VIA_HTTP
    )
    assert v == "ok" and consumer["name"] == "f1"

    _, v = distribution.resolve_submitter(
        db_conn, source="fleet:fleet_zzz/m_1", domain_key="legal", via=submitters.VIA_HTTP
    )
    assert v == "unregistered"

    _, v = distribution.resolve_submitter(
        db_conn, source="fleet:fleet_abc/m_1", domain_key="gov", via=submitters.VIA_HTTP
    )
    assert v == "domain_mismatch"


def test_resolve_submitter_extract_depends_on_channel(db_conn):
    """The single most important branch: in-process ok, external impersonation."""
    _, v = distribution.resolve_submitter(
        db_conn, source="extract:m:2026-11-09.1", domain_key="legal",
        via=submitters.VIA_IN_PROCESS,
    )
    assert v == "ok"
    _, v = distribution.resolve_submitter(
        db_conn, source="extract:m:2026-11-09.1", domain_key="legal",
        via=submitters.VIA_HTTP,
    )
    assert v == "pipeline_impersonation"


def test_resolve_submitter_agent_membership(db_conn):
    domain = _domain(db_conn)
    workspaces.add_member(
        db_conn, domain_id=domain["id"], user_id="agent:concept@legal",
        role="expert", added_by="tester",
    )

    _, v = distribution.resolve_submitter(
        db_conn, source="agent:concept@legal", domain_key="legal", via=submitters.VIA_HTTP
    )
    assert v == "ok"

    _, v = distribution.resolve_submitter(
        db_conn, source="agent:ghost@legal", domain_key="legal", via=submitters.VIA_HTTP
    )
    assert v == "agent_not_member"

    _, v = distribution.resolve_submitter(
        db_conn, source="agent:concept@gov", domain_key="legal", via=submitters.VIA_HTTP
    )
    assert v == "agent_domain_mismatch"


def test_resolve_submitter_unknown_and_malformed(db_conn):
    _, v = distribution.resolve_submitter(
        db_conn, source="wire:a/b", domain_key="legal", via=submitters.VIA_HTTP
    )
    assert v == "unknown_prefix"
    _, v = distribution.resolve_submitter(
        db_conn, source="fleet:no-slash", domain_key="legal", via=submitters.VIA_HTTP
    )
    assert v == "malformed"


def test_resolve_submitter_agrees_with_pure_judgement(db_conn):
    """Whatever the DB lookup returns, the verdict must be the pure one's.

    This is the guard against a second judgement implementation growing here:
    the 36 exhaustive cases live in test_submitter_contract.py, and this test
    ties the DB layer to that same vocabulary.
    """
    _domain(db_conn)
    distribution.register_consumer(
        db_conn, name="f1", domains=["legal"], token_hash="h12",
        created_by="admin", kind="fleet", fleet_ref="fleet_abc",
    )
    cases = [
        ("fleet:fleet_abc/m_1", {"fleet": {"domains": ["legal"], "revoked": False}}),
        ("fleet:fleet_zzz/m_1", {"fleet": None}),
        ("extract:m:v", {}),
        ("agent:who@legal", {"agent_is_member": False}),
        ("bogus", {}),
    ]
    for source, facts in cases:
        _, db_verdict = distribution.resolve_submitter(
            db_conn, source=source, domain_key="legal", via=submitters.VIA_HTTP
        )
        pure = submitters.verdict(
            source, domain_key="legal", via=submitters.VIA_HTTP, **facts
        )
        assert db_verdict == pure == submitters.verdict(
            source, domain_key="legal", via=submitters.VIA_HTTP, **facts
        ), source
