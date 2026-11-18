"""Knowledge distribution kernel surface (add-knowledge-distribution-contract, tasks 3.1-3.3 + 3.5 kernel half).

Covers the kernel-level semantics of ``src/bench/distribution.py`` (no HTTP):

- digest 稳定性 (3.1): canonical_digest is key-order insensitive and metadata
  sensitive; the real manifest carries NO generation metadata (published_at /
  published_by / version never enter the digest anchor); entries are sorted by
  external_key so the manifest is a content-pure function (same content
  inserted in different order across two fresh domains projects identically);
  different content yields a different digest.
- manifest 构造: template version + vocabularies anchored; soft-deleted units
  excluded; relationship entries carry the structured from_key/to_key that
  agree with the deterministic key convention (消费者侧身份重建); sensitivity
  mirrors tags.sensitivity (None when absent); a corrupt relationship (missing
  endpoints) fails publish loudly naming the unit.
- 发布语义 (3.2): v1 produces version 1 + initial changelog; empty domain and
  unknown domain refused without a row; version monotonic across edits;
  same-digest republish is idempotent (existing row returned, no new row) —
  including the revert-to-published-content case; the published v1 snapshot
  stays byte-identical (manifest/digest/changelog/published_at) after later
  edits; every manifest entry traces back to an authoring event trail.
- changelog (3.3): v2 carries added/removed/changed with field-level
  before/after (body, sensitivity, tier); v1 keeps its initial inventory
  unchanged after v2.
- 消费者 (3.5 kernel half): register -> lookup by hash; duplicate name
  refused; domain binding replaced as a whole group; revoke sets revoked_at
  (row still returned, web layer owns denial) and is idempotent; unknown name
  refused; token_hash-only storage — no plaintext token column exists.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.bench import authoring, distribution, templates, workspaces
from src.bench.store import upsert_knowledge_unit
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
    gate and the manifest projection read entity_types / relationship_kinds
    from exactly this data."""
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


def create_company(conn, domain_key: str, external_key: str, body: str, tags=None, attrs=None) -> dict:
    return authoring.authoring_create_unit(
        conn,
        domain_key=domain_key,
        kind="company",
        external_key=external_key,
        body=body,
        operator="expert-1",
        tags=tags,
        attrs=attrs,
    )


def create_indicator(conn, domain_key: str, external_key: str, body: str) -> dict:
    return authoring.authoring_create_unit(
        conn,
        domain_key=domain_key,
        kind="indicator",
        external_key=external_key,
        body=body,
        operator="expert-1",
    )


def create_rel(conn, domain_key: str, from_key: str, to_key: str, body: str) -> dict:
    return authoring.authoring_create_relationship(
        conn,
        domain_key=domain_key,
        kind="belongs_to",
        from_key=from_key,
        to_key=to_key,
        body=body,
        operator="expert-1",
    )


def seed_standard(conn, domain_key: str) -> None:
    """co-1, co-2, ind-1 entities plus one belongs_to relationship."""
    create_company(conn, domain_key, "co-1", "公司一")
    create_company(conn, domain_key, "co-2", "公司二")
    create_indicator(conn, domain_key, "ind-1", "指标一")
    create_rel(conn, domain_key, "co-1", "co-2", "隶属一")


def publication_count(conn, domain_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM ontology_publications WHERE domain_id = %s",
        (domain_id,),
    ).fetchone()
    return row["n"]


def stripped_content_digest(manifest: dict) -> str:
    """Digest over the content keys only — the per-domain identity key
    ('domain') is excluded so two domains carrying identical content can be
    compared for digest stability."""
    return distribution.canonical_digest(
        {k: v for k, v in manifest.items() if k != "domain"}
    )


# ---------------------------------------------------------------- digest 稳定性 (3.1)


def test_canonical_digest_key_order_insensitive_metadata_sensitive(db_conn):
    """规范 digest: 键序归一 → 同内容异构造序同 digest; 时间戳/发布者/版本号
    参与 digest 会改变它 —— 因此真实 manifest 必须排除它们; 异内容异 digest."""
    m1 = {"b": 2, "a": {"y": 1, "x": 2}}
    m2 = {"a": {"x": 2, "y": 1}, "b": 2}
    assert distribution.canonical_digest(m1) == distribution.canonical_digest(m2)

    # adding generation metadata to a COPY changes the digest
    for extra in ("published_at", "published_by", "version"):
        tampered = dict(m1)
        tampered[extra] = "now"
        assert distribution.canonical_digest(tampered) != distribution.canonical_digest(m1)

    # different content → different digest
    assert distribution.canonical_digest({"a": 1}) != distribution.canonical_digest({"a": 2})

    # deterministic across calls, non-ASCII content preserved
    assert distribution.canonical_digest({"body": "某公司条目"}) == distribution.canonical_digest(
        {"body": "某公司条目"}
    )


def test_build_manifest_shape_no_generation_metadata_and_template_anchor(db_conn):
    """manifest 契约面: 顶层键集合固定、无 published_at/published_by/version、
    模板版本锚定、词表随 manifest 携带、条目字段面符合 MANIFEST_FIELDS."""
    domain = make_domain(db_conn, "dom-shape")
    seed_standard(db_conn, "dom-shape")

    manifest, entities, relationships = distribution.build_manifest(
        db_conn, domain=workspaces.get_domain(db_conn, domain_key="dom-shape")
    )
    assert (entities, relationships) == (3, 1)
    assert set(manifest) == {
        "domain",
        "template_name",
        "template_version",
        "entity_types",
        "relationship_kinds",
        "entities",
        "relationships",
    }
    # the digest anchor is content-only: no generation metadata anywhere
    assert not {"published_at", "published_by", "version"} & set(manifest)
    assert manifest["template_version"] == domain["template_version"] == 1
    assert manifest["template_name"] == "tpl-dom-shape"
    assert manifest["entity_types"] == ["company", "indicator"]
    assert manifest["relationship_kinds"] == ["belongs_to"]

    entity_fields = {"kind", "external_key", "body", "tier", "sensitivity", "attrs"}
    relationship_fields = entity_fields | {"from_key", "to_key"}
    for entry in manifest["entities"]:
        assert set(entry) == entity_fields
        assert not {"published_at", "published_by", "version"} & set(entry)
    for entry in manifest["relationships"]:
        assert set(entry) == relationship_fields
        assert not {"published_at", "published_by", "version"} & set(entry)


def test_build_manifest_entries_sorted_by_external_key(db_conn):
    """条目按 external_key 排序: 插入序故意乱序 (后插入者 list 视图在前),
    manifest 输出仍按键序 — digest 只看内容不看落库顺序."""
    make_domain(db_conn, "dom-sorted")
    create_company(db_conn, "dom-sorted", "co-c", "公司丙")
    create_company(db_conn, "dom-sorted", "co-a", "公司甲")
    create_company(db_conn, "dom-sorted", "co-b", "公司乙")
    create_rel(db_conn, "dom-sorted", "co-a", "co-c", "隶属乙")  # created first
    create_rel(db_conn, "dom-sorted", "co-b", "co-c", "隶属甲")  # created second

    # evidence the underlying projections really are in non-sorted order
    # (authoring_list_units: most recently updated first)
    listed = [u["external_key"] for u in authoring.authoring_list_units(
        db_conn, domain_key="dom-sorted", kind="company"
    )]
    assert listed == ["co-b", "co-a", "co-c"]
    rel_listed = [u["external_key"] for u in authoring.authoring_list_units(
        db_conn, domain_key="dom-sorted", kind="belongs_to"
    )]
    assert rel_listed == ["co-b->belongs_to:co-c", "co-a->belongs_to:co-c"]

    manifest, _, _ = distribution.build_manifest(
        db_conn, domain=workspaces.get_domain(db_conn, domain_key="dom-sorted")
    )
    assert [e["external_key"] for e in manifest["entities"]] == ["co-a", "co-b", "co-c"]
    assert [e["external_key"] for e in manifest["relationships"]] == [
        "co-a->belongs_to:co-c",
        "co-b->belongs_to:co-c",
    ]


def test_manifest_content_pure_across_insert_order_publish(db_conn):
    """内容纯函数: 同一模板、两个新鲜域、同内容异插入序 → 发布出的 manifest
    除逐域身份键 'domain' 外完全一致, 内容 digest 相同; changelog 一致."""
    tmpl = templates.create_template(
        db_conn, name="tpl-order", schema=authoring_schema(), created_by="admin-1"
    )
    for key in ("dom-order-a", "dom-order-b"):
        workspaces.instantiate_domain(
            db_conn,
            key=key,
            name=f"Domain {key}",
            template_name="tpl-order",
            template_version=tmpl["version"],
            created_by="admin-1",
        )
    # A: co-2 first then co-1; B: relationship first then co-1 then co-2
    create_company(db_conn, "dom-order-a", "co-2", "公司二")
    create_company(db_conn, "dom-order-a", "co-1", "公司一")
    create_rel(db_conn, "dom-order-a", "co-1", "co-2", "隶属一")
    create_rel(db_conn, "dom-order-b", "co-1", "co-2", "隶属一")
    create_company(db_conn, "dom-order-b", "co-1", "公司一")
    create_company(db_conn, "dom-order-b", "co-2", "公司二")

    # the underlying list projections genuinely differ in order
    a_keys = [u["external_key"] for u in authoring.authoring_list_units(
        db_conn, domain_key="dom-order-a", kind="company"
    )]
    b_keys = [u["external_key"] for u in authoring.authoring_list_units(
        db_conn, domain_key="dom-order-b", kind="company"
    )]
    assert a_keys == ["co-1", "co-2"]  # newest first
    assert b_keys == ["co-2", "co-1"]

    p_a = distribution.publish_domain(db_conn, domain_key="dom-order-a", published_by="lead-1")
    p_b = distribution.publish_domain(db_conn, domain_key="dom-order-b", published_by="lead-1")
    ma, mb = p_a["manifest"], p_b["manifest"]

    # identity differs, content does not: 'domain' is the ONLY differing key
    differing = {k for k in set(ma) | set(mb) if ma.get(k) != mb.get(k)}
    assert differing == {"domain"}
    # so the content-only digests are identical
    assert stripped_content_digest(ma) == stripped_content_digest(mb)
    # and publish anchored its own manifest exactly
    assert p_a["digest"] == distribution.canonical_digest(ma)
    assert p_a["changelog"] == p_b["changelog"] == {
        "initial": True,
        "counts": {"entities": 2, "relationships": 1},
    }


# ---------------------------------------------------------------- manifest 构造


def test_build_manifest_excludes_soft_deleted_units(db_conn):
    """软删项不出现在 manifest (spec: 发布产生可拉取版本): 实体与关系软删后
    均被快照投影排除, changelog counts 描述剪除后的快照."""
    make_domain(db_conn, "dom-softdel")
    seed_standard(db_conn, "dom-softdel")
    authoring.authoring_delete_unit(
        db_conn, domain_key="dom-softdel", kind="indicator",
        external_key="ind-1", operator="expert-2",
    )
    authoring.authoring_delete_relationship(
        db_conn, domain_key="dom-softdel", kind="belongs_to",
        from_key="co-1", to_key="co-2", operator="expert-2",
    )

    manifest, entities, relationships = distribution.build_manifest(
        db_conn, domain=workspaces.get_domain(db_conn, domain_key="dom-softdel")
    )
    assert [e["external_key"] for e in manifest["entities"]] == ["co-1", "co-2"]
    assert manifest["relationships"] == []
    assert (entities, relationships) == (2, 0)

    # publish level agrees: counts describe the pruned snapshot
    pub = distribution.publish_domain(db_conn, domain_key="dom-softdel", published_by="lead-1")
    assert pub["changelog"]["counts"] == {"entities": 2, "relationships": 0}
    assert all(e["external_key"] != "ind-1" for e in pub["manifest"]["entities"])


def test_relationship_entries_carry_structured_endpoints_key_convention(db_conn):
    """契约锚 (消费者侧身份重建): 关系条目携带结构化 from_key/to_key, 且与
    确定性键约定 {from_key}->{kind}:{to_key} 一致 — 无需第二套身份解析."""
    make_domain(db_conn, "dom-relkey")
    create_company(db_conn, "dom-relkey", "co-1", "公司一")
    create_company(db_conn, "dom-relkey", "co-2", "公司二")
    create_rel(db_conn, "dom-relkey", "co-1", "co-2", "隶属一")

    manifest, _, _ = distribution.build_manifest(
        db_conn, domain=workspaces.get_domain(db_conn, domain_key="dom-relkey")
    )
    assert len(manifest["relationships"]) == 1
    entry = manifest["relationships"][0]
    assert entry["kind"] == "belongs_to"
    assert entry["external_key"] == "co-1->belongs_to:co-2"
    assert entry["from_key"] == "co-1"
    assert entry["to_key"] == "co-2"
    # key convention and structured endpoints rebuild the same identity
    assert entry["external_key"] == (
        f"{entry['from_key']}->{entry['kind']}:{entry['to_key']}"
    )


def test_entry_sensitivity_mirrors_tags_none_when_absent(db_conn):
    """sensitivity 从 tags 读取 (缺省 null), attrs 原样携带, tier 为创作面 raw."""
    make_domain(db_conn, "dom-sens")
    create_company(db_conn, "dom-sens", "co-1", "公司一", tags={"sensitivity": "internal", "theme": "x"})
    create_company(db_conn, "dom-sens", "co-2", "公司二")
    create_company(db_conn, "dom-sens", "co-3", "公司三", attrs={"hq": "北京"})

    manifest, _, _ = distribution.build_manifest(
        db_conn, domain=workspaces.get_domain(db_conn, domain_key="dom-sens")
    )
    by_key = {e["external_key"]: e for e in manifest["entities"]}
    assert by_key["co-1"]["sensitivity"] == "internal"
    assert by_key["co-2"]["sensitivity"] is None  # absent tag → null on the contract
    assert by_key["co-3"]["attrs"] == {"hq": "北京"}
    assert all(e["tier"] == "raw" for e in manifest["entities"])


def test_corrupt_relationship_missing_endpoints_fails_loudly(db_conn):
    """坏数据拒绝发布: 关系条目缺结构化端点 → build_manifest / publish 均报错
    且点名该单元 — 绝不发布消费者无法解码的快照."""
    domain = make_domain(db_conn, "dom-corrupt")
    create_company(db_conn, "dom-corrupt", "co-1", "公司一")
    create_company(db_conn, "dom-corrupt", "co-2", "公司二")
    # corrupt stored data inserted directly: a relationship unit without endpoints
    upsert_knowledge_unit(
        db_conn,
        kind="belongs_to",
        external_key="broken->belongs_to:co-2",
        body="坏数据",
        namespace="dom-corrupt",
        tags={},
        attrs={},
        tier="raw",
        provenance={"operator": "bypass", "via": "direct"},
    )

    with pytest.raises(ValueError) as exc:
        distribution.build_manifest(
            db_conn, domain=workspaces.get_domain(db_conn, domain_key="dom-corrupt")
        )
    message = str(exc.value)
    assert "broken->belongs_to:co-2" in message
    assert "from_key" in message
    assert "dom-corrupt" in message

    # publish refuses loudly as well — no snapshot row can be produced
    with pytest.raises(ValueError, match="broken->belongs_to:co-2"):
        distribution.publish_domain(db_conn, domain_key="dom-corrupt", published_by="lead-1")
    assert publication_count(db_conn, domain["id"]) == 0


# ---------------------------------------------------------------- 发布语义 (3.2)


def test_publish_v1_version_digest_and_initial_changelog(db_conn):
    """首版发布: version=1, changelog 为初始清单, digest 锚定 manifest 内容,
    与 build_manifest 输出一致; published_by 缺失拒绝."""
    make_domain(db_conn, "dom-publish")
    seed_standard(db_conn, "dom-publish")

    with pytest.raises(ValueError, match="published_by"):
        distribution.publish_domain(db_conn, domain_key="dom-publish", published_by="")

    pub = distribution.publish_domain(db_conn, domain_key="dom-publish", published_by="lead-1")
    assert pub["version"] == 1
    assert pub["published_by"] == "lead-1"
    datetime.fromisoformat(pub["published_at"])
    assert pub["changelog"] == {"initial": True, "counts": {"entities": 3, "relationships": 1}}
    # digest anchors exactly the manifest content
    assert pub["digest"] == distribution.canonical_digest(pub["manifest"])

    built, entities, relationships = distribution.build_manifest(
        db_conn, domain=workspaces.get_domain(db_conn, domain_key="dom-publish")
    )
    assert pub["manifest"] == built
    assert (entities, relationships) == (3, 1)

    latest = distribution.get_publication(db_conn, domain_key="dom-publish")
    assert latest["id"] == pub["id"]
    assert latest["version"] == 1


def test_publish_empty_domain_refused_and_no_version_row(db_conn):
    """空域发布拒绝 (spec): 报明域内无内容, 不产生空版本; 未知域同样拒绝."""
    domain = make_domain(db_conn, "dom-empty")
    with pytest.raises(ValueError, match="no content"):
        distribution.publish_domain(db_conn, domain_key="dom-empty", published_by="lead-1")
    assert distribution.list_publications(db_conn, domain_key="dom-empty") == []
    assert publication_count(db_conn, domain["id"]) == 0

    with pytest.raises(ValueError, match="not found"):
        distribution.publish_domain(db_conn, domain_key="dom-ghost", published_by="lead-1")


def test_version_monotonic_across_edits(db_conn):
    """版本号单调: 每次内容变更后发布版本 +1, digest 随内容变化, 历史版本
    全量可列."""
    make_domain(db_conn, "dom-mono")
    seed_standard(db_conn, "dom-mono")
    v1 = distribution.publish_domain(db_conn, domain_key="dom-mono", published_by="lead-1")
    assert v1["version"] == 1

    authoring.authoring_update_unit(
        db_conn, domain_key="dom-mono", kind="company",
        external_key="co-1", body="公司一改", operator="expert-2",
    )
    create_company(db_conn, "dom-mono", "co-3", "公司三")
    v2 = distribution.publish_domain(db_conn, domain_key="dom-mono", published_by="lead-1")
    assert v2["version"] == 2
    assert v2["digest"] != v1["digest"]

    create_rel(db_conn, "dom-mono", "co-1", "co-2", "隶属一改")
    v3 = distribution.publish_domain(db_conn, domain_key="dom-mono", published_by="lead-1")
    assert v3["version"] == 3
    assert v3["digest"] not in {v1["digest"], v2["digest"]}

    versions = [p["version"] for p in distribution.list_publications(
        db_conn, domain_key="dom-mono"
    )]
    assert versions == [1, 2, 3]
    assert distribution.get_publication(db_conn, domain_key="dom-mono")["version"] == 3


def test_republish_same_content_idempotent_no_new_row(db_conn):
    """同内容重复发布幂等 (spec): 返回既有版本与既有 digest, 不产生新快照行;
    既有行的发布者不被改写."""
    domain = make_domain(db_conn, "dom-idem")
    seed_standard(db_conn, "dom-idem")
    distribution.publish_domain(db_conn, domain_key="dom-idem", published_by="lead-1")
    authoring.authoring_update_unit(
        db_conn, domain_key="dom-idem", kind="company",
        external_key="co-1", body="公司一改", operator="expert-2",
    )
    v2 = distribution.publish_domain(db_conn, domain_key="dom-idem", published_by="lead-2")

    # zero-change republish: the EXISTING row comes back as-is
    republished = distribution.publish_domain(db_conn, domain_key="dom-idem", published_by="lead-3")
    assert republished["id"] == v2["id"]
    assert republished["version"] == 2
    assert republished["digest"] == v2["digest"]
    assert republished["changelog"] == v2["changelog"]
    assert republished["published_by"] == v2["published_by"] == "lead-2"

    assert publication_count(db_conn, domain["id"]) == 2
    versions = [p["version"] for p in distribution.list_publications(
        db_conn, domain_key="dom-idem"
    )]
    assert versions == [1, 2]


def test_revert_to_published_content_returns_that_version_no_new_row(db_conn):
    """digest 键幂等的推论: 内容改回某个已发布状态再发布 → 返回那一版的行
    (v2), 即使 v3 已存在也不产生新行, 最新版本仍是 v3."""
    domain = make_domain(db_conn, "dom-revert")
    seed_standard(db_conn, "dom-revert")
    distribution.publish_domain(db_conn, domain_key="dom-revert", published_by="lead-1")
    authoring.authoring_update_unit(
        db_conn, domain_key="dom-revert", kind="company",
        external_key="co-1", body="第二版", operator="expert-2",
    )
    v2 = distribution.publish_domain(db_conn, domain_key="dom-revert", published_by="lead-1")
    authoring.authoring_update_unit(
        db_conn, domain_key="dom-revert", kind="company",
        external_key="co-1", body="第三版", operator="expert-2",
    )
    v3 = distribution.publish_domain(db_conn, domain_key="dom-revert", published_by="lead-1")
    assert v3["version"] == 3

    # content returns to exactly the v2 state, then publish
    authoring.authoring_update_unit(
        db_conn, domain_key="dom-revert", kind="company",
        external_key="co-1", body="第二版", operator="expert-3",
    )
    returned = distribution.publish_domain(db_conn, domain_key="dom-revert", published_by="lead-1")
    assert returned["version"] == 2
    assert returned["id"] == v2["id"]
    assert returned["digest"] == v2["digest"]

    assert publication_count(db_conn, domain["id"]) == 3
    assert distribution.get_publication(db_conn, domain_key="dom-revert")["version"] == 3


def test_published_v1_snapshot_immutable_after_later_edits(db_conn):
    """快照不可变 (spec: 逐字节一致): v1 发布后继续编辑, v1 的 manifest /
    digest / changelog / published_at 完全不变, 且存储行重算 digest 与发布时
    一致; 内核不暴露任何发布改写/删除路径."""
    domain = make_domain(db_conn, "dom-frozen")
    seed_standard(db_conn, "dom-frozen")
    v1 = distribution.publish_domain(db_conn, domain_key="dom-frozen", published_by="lead-1")
    v1_manifest, v1_digest, v1_changelog = v1["manifest"], v1["digest"], v1["changelog"]

    # publish, then keep editing: body change, new entity, soft delete
    authoring.authoring_update_unit(
        db_conn, domain_key="dom-frozen", kind="company",
        external_key="co-1", body="公司一改", operator="expert-2",
    )
    create_company(db_conn, "dom-frozen", "co-3", "公司三")
    authoring.authoring_delete_unit(
        db_conn, domain_key="dom-frozen", kind="indicator",
        external_key="ind-1", operator="expert-2",
    )
    v2 = distribution.publish_domain(db_conn, domain_key="dom-frozen", published_by="lead-1")
    assert v2["version"] == 2
    assert v2["digest"] != v1_digest

    fetched = distribution.get_publication(db_conn, domain_key="dom-frozen", version=1)
    assert fetched["manifest"] == v1_manifest
    assert fetched["digest"] == v1_digest
    assert fetched["changelog"] == v1_changelog
    assert fetched["id"] == v1["id"]
    assert fetched["published_at"] == v1["published_at"]
    # content anchor: recomputing the digest over the stored manifest agrees
    assert distribution.canonical_digest(fetched["manifest"]) == v1_digest

    # physical evidence: the append-only row itself still carries the v1 digest
    row = db_conn.execute(
        "SELECT digest, manifest FROM ontology_publications "
        "WHERE domain_id = %s AND version = 1",
        (domain["id"],),
    ).fetchone()
    assert row["digest"] == v1_digest
    assert distribution.canonical_digest(row["manifest"]) == v1_digest

    # the kernel surface has no publication mutation path (append-only)
    assert not [
        n for n in dir(distribution)
        if n.startswith(("delete_publication", "update_publication", "unpublish"))
    ]


def test_published_entries_trace_to_authoring_events(db_conn):
    """对账 (spec): 发布的每条内容可回指其事件史 — manifest 中每个键都能查到
    非空事件轨迹; 抽查 co-1 的轨迹为 update+create (newest first)."""
    domain = make_domain(db_conn, "dom-trace")
    seed_standard(db_conn, "dom-trace")
    authoring.authoring_update_unit(
        db_conn, domain_key="dom-trace", kind="company",
        external_key="co-1", body="公司一改", operator="expert-2",
    )
    pub = distribution.publish_domain(db_conn, domain_key="dom-trace", published_by="lead-1")
    manifest = pub["manifest"]
    keys = [e["external_key"] for e in manifest["entities"]] + [
        e["external_key"] for e in manifest["relationships"]
    ]
    assert sorted(keys) == ["co-1", "co-1->belongs_to:co-2", "co-2", "ind-1"]

    for key in keys:
        trail = authoring.authoring_events_for(db_conn, domain_id=domain["id"], unit_key=key)
        assert trail, f"manifest entry {key!r} has no authoring event trail"

    co1 = authoring.authoring_events_for(
        db_conn, domain_id=domain["id"], unit_kind="company", unit_key="co-1"
    )
    assert [e["op"] for e in co1] == ["update", "create"]
    rel = authoring.authoring_events_for(
        db_conn, domain_id=domain["id"], unit_key="co-1->belongs_to:co-2"
    )
    assert [e["op"] for e in rel] == ["create"]


# ---------------------------------------------------------------- changelog (3.3)


def test_v2_changelog_added_removed_changed_and_v1_frozen(db_conn):
    """二版携带差异 (spec): v2 changelog 含新增实体、删除指标、两条字段级
    变更 (实体 body 与关系 body); v1 changelog 保持初始清单不变."""
    make_domain(db_conn, "dom-changelog")
    seed_standard(db_conn, "dom-changelog")
    v1 = distribution.publish_domain(db_conn, domain_key="dom-changelog", published_by="lead-1")
    assert v1["changelog"] == {"initial": True, "counts": {"entities": 3, "relationships": 1}}

    # expert adds one entity, removes one indicator, edits one entity and one relationship
    create_company(db_conn, "dom-changelog", "co-3", "公司三")
    authoring.authoring_delete_unit(
        db_conn, domain_key="dom-changelog", kind="indicator",
        external_key="ind-1", operator="expert-2",
    )
    authoring.authoring_update_unit(
        db_conn, domain_key="dom-changelog", kind="company",
        external_key="co-1", body="公司一改", operator="expert-2",
    )
    create_rel(db_conn, "dom-changelog", "co-1", "co-2", "隶属一改")

    v2 = distribution.publish_domain(db_conn, domain_key="dom-changelog", published_by="lead-1")
    assert v2["version"] == 2
    cl = v2["changelog"]
    assert cl["added"] == ["co-3"]
    assert cl["removed"] == ["ind-1"]
    assert cl["changed"] == [
        {
            "key": "co-1",
            "kind": "company",
            "fields": {"body": {"before": "公司一", "after": "公司一改"}},
        },
        {
            "key": "co-1->belongs_to:co-2",
            "kind": "belongs_to",
            "fields": {"body": {"before": "隶属一", "after": "隶属一改"}},
        },
    ]
    assert cl["counts"] == {"entities": 3, "relationships": 1}

    # v1 changelog frozen: not rewritten by the later publish
    v1_after = distribution.get_publication(db_conn, domain_key="dom-changelog", version=1)
    assert v1_after["changelog"] == {
        "initial": True,
        "counts": {"entities": 3, "relationships": 1},
    }


def test_changelog_changed_detects_tier_and_sensitivity(db_conn):
    """字段级差异覆盖 tier 与 sensitivity: sensitivity 经创作面编辑
    (internal→confidential); 创作面总是把 tier 重置为 raw, 故 tier 变更
    (raw→gold) 经 store 直接驱动一次以覆盖 diff 的档位字段."""
    make_domain(db_conn, "dom-diff-meta")
    create_company(db_conn, "dom-diff-meta", "co-sens", "敏感公司", tags={"sensitivity": "internal"})
    create_company(db_conn, "dom-diff-meta", "co-tier", "档位公司")
    distribution.publish_domain(db_conn, domain_key="dom-diff-meta", published_by="lead-1")

    authoring.authoring_update_unit(
        db_conn, domain_key="dom-diff-meta", kind="company",
        external_key="co-sens", body="敏感公司", operator="expert-2",
        tags={"sensitivity": "confidential"},
    )
    upsert_knowledge_unit(
        db_conn,
        kind="company",
        external_key="co-tier",
        body="档位公司",
        namespace="dom-diff-meta",
        tags=None,
        attrs=None,
        tier="gold",
        provenance={"operator": "annotator", "via": "promotion"},
    )
    v2 = distribution.publish_domain(db_conn, domain_key="dom-diff-meta", published_by="lead-1")
    cl = v2["changelog"]
    assert cl["added"] == []
    assert cl["removed"] == []
    assert cl["changed"] == [
        {
            "key": "co-sens",
            "kind": "company",
            "fields": {"sensitivity": {"before": "internal", "after": "confidential"}},
        },
        {
            "key": "co-tier",
            "kind": "company",
            "fields": {"tier": {"before": "raw", "after": "gold"}},
        },
    ]

    # the v2 manifest itself carries the moved values
    entries = {e["external_key"]: e for e in v2["manifest"]["entities"]}
    assert entries["co-sens"]["sensitivity"] == "confidential"
    assert entries["co-tier"]["tier"] == "gold"


# ---------------------------------------------------------------- 消费者 (3.5 kernel half)


def test_register_consumer_lookup_by_hash_and_duplicate_name_refused(db_conn):
    """登记与凭据查找: 按 token_hash 精确命中, 未登记哈希返回 None, 重名拒绝."""
    created = distribution.register_consumer(
        db_conn, name="wire", domains=["legal"], token_hash="a" * 64, created_by="admin-1"
    )
    assert created["name"] == "wire"
    assert created["domains"] == ["legal"]
    assert created["token_hash"] == "a" * 64
    assert created["created_by"] == "admin-1"
    assert created["revoked_at"] is None
    datetime.fromisoformat(created["created_at"])

    found = distribution.get_consumer_by_token_hash(db_conn, token_hash="a" * 64)
    assert found is not None
    assert found["id"] == created["id"]
    assert found["token_hash"] == "a" * 64
    assert distribution.get_consumer_by_token_hash(db_conn, token_hash="b" * 64) is None

    with pytest.raises(ValueError, match="already exists"):
        distribution.register_consumer(
            db_conn, name="wire", domains=["fin"], token_hash="c" * 64, created_by="admin-1"
        )
    assert [c["name"] for c in distribution.list_consumers(db_conn)] == ["wire"]


def test_set_consumer_domains_replaces_whole_group(db_conn):
    """绑定域整组替换: 新列表完全覆盖旧列表 (旧域消失), 查找行同步反映."""
    distribution.register_consumer(
        db_conn, name="wire", domains=["legal"], token_hash="a" * 64, created_by="admin-1"
    )
    replaced = distribution.set_consumer_domains(db_conn, name="wire", domains=["fin", "legal"])
    assert replaced["domains"] == ["fin", "legal"]
    looked_up = distribution.get_consumer_by_token_hash(db_conn, token_hash="a" * 64)
    assert looked_up["domains"] == ["fin", "legal"]

    # whole-group replace: setting only fin removes legal
    narrowed = distribution.set_consumer_domains(db_conn, name="wire", domains=["fin"])
    assert narrowed["domains"] == ["fin"]
    assert "legal" not in distribution.get_consumer_by_token_hash(
        db_conn, token_hash="a" * 64
    )["domains"]

    # an empty binding group is allowed
    assert distribution.set_consumer_domains(db_conn, name="wire", domains=[])["domains"] == []


def test_revoke_sets_revoked_at_lookup_returns_row_and_is_idempotent(db_conn):
    """吊销: revoked_at 落定; 内核查找仍返回该行 (web 层据 revoked_at 决定拒绝);
    重复吊销幂等 — 时间戳不移动."""
    distribution.register_consumer(
        db_conn, name="wire", domains=["legal"], token_hash="a" * 64, created_by="admin-1"
    )
    revoked = distribution.revoke_consumer(db_conn, name="wire")
    assert revoked["revoked_at"] is not None
    datetime.fromisoformat(revoked["revoked_at"])

    still = distribution.get_consumer_by_token_hash(db_conn, token_hash="a" * 64)
    assert still is not None
    assert still["revoked_at"] == revoked["revoked_at"]

    again = distribution.revoke_consumer(db_conn, name="wire")
    assert again["revoked_at"] == revoked["revoked_at"]


def test_unknown_consumer_name_refused(db_conn):
    """未知消费者名: 域绑定替换与吊销均拒绝."""
    with pytest.raises(ValueError, match="not found"):
        distribution.set_consumer_domains(db_conn, name="ghost", domains=["legal"])
    with pytest.raises(ValueError, match="not found"):
        distribution.revoke_consumer(db_conn, name="ghost")


def test_token_hash_only_storage_no_plaintext_column(db_conn):
    """凭据纪律: 内核只存给入的哈希; 返回行与物理表都没有明文令牌字段."""
    fake_hash = "deadbeef" * 8
    created = distribution.register_consumer(
        db_conn, name="wire", domains=["legal"], token_hash=fake_hash, created_by="admin-1"
    )
    # the kernel stores exactly the digest it was given
    assert created["token_hash"] == fake_hash
    # the projected row exposes no plaintext-token field at all
    # (``kind``/``fleet_ref`` joined this projection in add-fleet-execution-loop:
    # a fleet registration carries a stable ref, a machine one is refused for
    # carrying it at all — neither is a credential field.)
    assert set(created) == {
        "id", "name", "domains", "token_hash", "created_by", "created_at", "revoked_at",
        "kind", "fleet_ref",
    }
    assert not any("token" in k and k != "token_hash" for k in created)

    # physical evidence: the table itself has no plaintext column
    columns = {
        r["column_name"]
        for r in db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'distribution_consumers'"
        ).fetchall()
    }
    assert "token_hash" in columns
    assert not any("token" in c and c != "token_hash" for c in columns)
