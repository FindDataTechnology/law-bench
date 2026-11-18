"""Web tests for the knowledge-distribution surface (change
``add-knowledge-distribution-contract``).

Covers the machine pull face (OpenSpec task 3.4 — spec
``knowledge-distribution`` Requirement 机器拉取面: three-state auth + payload
contract) and the admin side (publish RBAC two-gate, consumer registry),
through HTTP only.

Two client patterns, per the established suite conventions:

- ``_client(db, user)`` (à la ``test_admin_web.py``) — ``create_app()`` with
  ``dependency_overrides`` for ``get_db`` + ``get_current_user``; used for
  every Logto-side action (publish as the domain lead, consumer registry as
  the platform admin, RBAC denial checks).
- ``_bare_client(db)`` — ONLY ``get_db`` is overridden: the REAL
  ``get_current_user`` runs with zero cookies and zero headers. The pull
  endpoint sits in ``_EXEMPT_PREFIXES`` (``/api/v1/distribution/`` in
  ``src/web/auth/deps.py``), so it resolves the anonymous sentinel and the
  route's own ``X-Consumer-Token`` three-state check IS the authentication —
  this is what makes the surface machine-callable without a Logto session.

Locale: the suite runs with the default ``zh`` catalog; flash assertions
target the ``msg`` key of the redirect Location (dotted i18n key) plus, where
the rendered text matters, the zh strings of ``src/web/i18n.py``.

World (seeded via the kernel APIs — ``src.bench.templates`` /
``workspaces`` / ``authoring``): one template; domain A ``dist-a-key`` with
two entities (``alpha-corp`` carrying sensitivity+attrs, ``beta-corp`` bare)
and one relationship (``alpha-corp->belongs_to:beta-corp``), members
lara=lead / alice=expert; domain B ``dist-b-key`` with one entity
(``gamma-corp``) and its own lead mark. Both domains anchor the SAME template
— vocabulary alignment is load-bearing for the publish manifest.

``knowledge_units`` is NOT in ``conftest._ALL_TABLES`` (no truncate between
tests), so ``_seed_world`` clears this module's namespaces directly (same
practice as ``test_authoring_web.py``).
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest
import yaml
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import authoring as bench_authoring
from src.bench import templates as bench_templates
from src.bench import workspaces
from src.settings import AUTH_COOKIE_NAME
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

# A structurally complete template schema (all four vocabularies + the corpus
# declaration); tier/sensitivity sets must equal the kernel's canonical tuples.
VALID_SCHEMA = {
    "entity_types": ["company"],
    "concept_structures": {"indicator": ["name", "unit"]},
    "relationship_kinds": ["belongs_to"],
    "tier_vocabulary": ["gold", "silver", "bronze", "raw"],
    "sensitivity_vocabulary": ["public", "internal", "confidential"],
    "corpus_declaration": {"source_types": []},
}

TEMPLATE_NAME = "distribution-template"
A_KEY = "dist-a-key"  # lara (lead) + alice (expert); 2 entities + 1 relationship
B_KEY = "dist-b-key"  # mark (lead, separate membership); 1 entity

DOMAIN_A_NAME = "甲域"
DOMAIN_B_NAME = "乙域"

A_BODY_1 = "甲域一号实体正文"
A_BODY_1_EDITED = "甲域一号实体正文·修订"
A_BODY_2 = "甲域二号实体正文"
REL_BODY = "甲域隶属关系"
B_BODY_1 = "乙域唯一实体正文"

ENTITY_A1 = "alpha-corp"
ENTITY_A2 = "beta-corp"
ENTITY_B1 = "gamma-corp"
REL_KEY = f"{ENTITY_A1}->belongs_to:{ENTITY_A2}"  # authoring key convention

_READ_WRITE = ["content:read", "content:write"]

# A payload-content vocabulary used ONLY for leak sweeps: none of these strings
# may appear in any error response (401/403/404) of the pull face.
_A_CONTENT = (ENTITY_A1, ENTITY_A2, REL_KEY, A_BODY_1, A_BODY_2, "c1-legacy")
_B_CONTENT = (ENTITY_B1, B_BODY_1)


# --- seed + client helpers -------------------------------------------------- #


def _seed_world(conn) -> dict:
    """One template, two domains; A: lara=lead alice=expert, B: mark=lead.

    A carries 2 entities + 1 relationship; B carries 1 entity. All content is
    written through the authoring kernel APIs (never raw SQL) so the publish
    manifest projects exactly what the authoring surface produced.
    """
    conn.execute(
        "DELETE FROM knowledge_units WHERE namespace IN (%s, %s)", (A_KEY, B_KEY)
    )
    conn.commit()
    bench_templates.create_template(
        conn, name=TEMPLATE_NAME, schema=dict(VALID_SCHEMA), created_by="seed"
    )
    a = workspaces.instantiate_domain(
        conn, key=A_KEY, name=DOMAIN_A_NAME,
        template_name=TEMPLATE_NAME, template_version=None, created_by="seed",
    )
    b = workspaces.instantiate_domain(
        conn, key=B_KEY, name=DOMAIN_B_NAME,
        template_name=TEMPLATE_NAME, template_version=None, created_by="seed",
    )
    workspaces.add_member(conn, domain_id=a["id"], user_id="lara", role="lead", added_by="seed")
    workspaces.add_member(conn, domain_id=a["id"], user_id="alice", role="expert", added_by="seed")
    workspaces.add_member(conn, domain_id=b["id"], user_id="mark", role="lead", added_by="seed")

    bench_authoring.authoring_create_unit(
        conn, domain_key=A_KEY, kind="company", external_key=ENTITY_A1,
        body=A_BODY_1, operator="alice",
        tags={"status": "draft", "sensitivity": "public"},
        attrs={"legacy_id": "c1-legacy"},
    )
    bench_authoring.authoring_create_unit(
        conn, domain_key=A_KEY, kind="company", external_key=ENTITY_A2,
        body=A_BODY_2, operator="alice",
    )
    bench_authoring.authoring_create_relationship(
        conn, domain_key=A_KEY, kind="belongs_to",
        from_key=ENTITY_A1, to_key=ENTITY_A2, body=REL_BODY, operator="alice",
    )
    bench_authoring.authoring_create_unit(
        conn, domain_key=B_KEY, kind="company", external_key=ENTITY_B1,
        body=B_BODY_1, operator="mark",
    )
    return {"a": a, "b": b}


def _user(sub: str, scopes: list[str]) -> User:
    """Override-pattern identity; ``_operator_of`` stamps ``user.email``."""
    return User(
        sub=sub, name=sub, email=f"{sub}@example.com",
        scopes=list(scopes), channel="test",
    )


def _client(db, user: User) -> TestClient:
    """App with ``get_db`` + ``get_current_user`` overridden to ``user``.

    Mirrors the real dependency's chrome contract by setting
    ``request.state.user`` (nav / ``has_scope`` read it).
    """
    app = create_app()

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


def _bare_client(db) -> TestClient:
    """Machine-surface client: ``get_db`` overridden ONLY.

    No identity override, no cookies — the real ``get_current_user`` runs and
    must exempt ``/api/v1/distribution/`` (anonymous sentinel), leaving the
    route's own token check as the sole authentication.
    """
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    """Neutralize the fail-closed startup IdP probe for every app built here."""
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _params(location: str) -> dict:
    """Flash query params of a redirect Location, decoded."""
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _publish(client: TestClient, domain_key: str, *, expect: str = "flash.published") -> dict:
    """POST the publish action as the client's user; return the flash params."""
    r = client.post(
        f"/admin/domains/{domain_key}/publish", data={}, follow_redirects=False
    )
    assert r.status_code == 303, r.text
    params = _params(r.headers["location"])
    assert params["msg"] == expect, params
    return params


def _register_consumer(admin: TestClient, name: str, domains: str) -> str:
    """Register a consumer via the admin form; return the plaintext token.

    The plaintext exists exactly once — in the creation flash (asserted here
    on the redirect Location; the followed-page / later-render discipline is
    test 13's subject).
    """
    r = admin.post(
        "/admin/distribution/consumers",
        data={"name": name, "domains": domains},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    params = _params(r.headers["location"])
    assert params["msg"] == "flash.consumer_registered", params
    assert params["name"] == name
    token = params["detail"]
    assert r.headers["location"].count(token) == 1  # shown exactly once
    return token


def _pull(client: TestClient, domain_key: str, token: str | None = None, **query) :
    """GET the machine pull endpoint; ``token`` rides X-Consumer-Token."""
    headers = {"X-Consumer-Token": token} if token is not None else {}
    return client.get(
        f"/api/v1/distribution/{domain_key}/ontology",
        params=query or None, headers=headers,
    )


# =========================================================================== #
# Task 3.4 — 机器拉取面: 三态鉴权 + payload 契约                                #
# =========================================================================== #


def test_pull_without_token_is_401_naming_the_header(seeded_db):
    """无凭据 401: the missing-credential state names the X-Consumer-Token
    header (the caller can tell WHAT to present), and no content appears."""
    _seed_world(seeded_db)
    with _bare_client(seeded_db) as bare:
        r = _pull(bare, A_KEY)
    assert r.status_code == 401
    assert r.json()["detail"] == "缺少机器凭据：X-Consumer-Token 请求头"
    assert "X-Consumer-Token" in r.json()["detail"]
    assert ENTITY_A1 not in r.text and A_BODY_1 not in r.text


def test_pull_unknown_and_revoked_tokens_are_distinct_403s(seeded_db):
    """令牌未登记 vs 令牌已吊销: two honestly-distinct 403 states.

    A garbage token was never registered; a registered-then-revoked token is
    a different fact (the spec scenario 「吊销后同令牌请求被拒（403 如实报
    「令牌已吊销」）」). The revoked token still 200s BEFORE revocation, so
    the denial is caused by the revocation itself.
    """
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        token = _register_consumer(admin, "wire", A_KEY)
        admin.post(
            "/admin/distribution/consumers/wire/revoke",
            data={}, follow_redirects=False,
        )

    with _bare_client(seeded_db) as bare:
        garbage = _pull(bare, A_KEY, token="never-registered-token")
        assert garbage.status_code == 403
        assert garbage.json()["detail"] == "令牌未登记"

        revoked = _pull(bare, A_KEY, token=token)
    assert revoked.status_code == 403
    assert revoked.json()["detail"] == "令牌已吊销"
    assert revoked.json()["detail"] != garbage.json()["detail"]  # distinct states
    # Credential discipline: no error ever echoes the plaintext token.
    assert token not in garbage.text and token not in revoked.text


def test_pull_out_of_scope_is_403_and_leaks_zero_domain_content(seeded_db):
    """越域 403: a consumer bound ONLY to B requesting A is denied with the
    out-of-scope message, and A's content (keys, bodies, relationship key,
    attrs) appears nowhere in the response."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        token = _register_consumer(admin, "peeker", B_KEY)

    with _bare_client(seeded_db) as bare:
        r = _pull(bare, A_KEY, token=token)
    assert r.status_code == 403
    assert r.json()["detail"] == "该域不在绑定范围"
    for fragment in _A_CONTENT:
        assert fragment not in r.text
    assert token not in r.text  # the credential itself is never echoed


def test_pull_payload_contract_shape_and_relationship_convention(seeded_db):
    """payload 契约: exact top-level keys, per-entry contract surface
    (tier/sensitivity/attrs), the deterministic relationship key convention
    ``{from}->{kind}:{to}`` with structured from/to, and the initial
    changelog of the first publication."""
    world = _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        page = lara.post(
            f"/admin/domains/{A_KEY}/publish", data={}, follow_redirects=True
        )
        assert page.status_code == 200
        assert "发布完成" in page.text  # flash renders on the domain detail page
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        token = _register_consumer(admin, "wire", A_KEY)

    with _bare_client(seeded_db) as bare:
        r = _pull(bare, A_KEY, token=token)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")

    payload = r.json()
    # The exact contract fd-wire codes against — no more, no less.
    assert set(payload) == {
        "domain", "template_name", "template_version",
        "publication_version", "digest",
        "entities", "relationships", "changelog",
    }
    assert payload["domain"] == A_KEY
    assert payload["template_name"] == TEMPLATE_NAME
    assert payload["template_version"] == world["a"]["template_version"] == 1
    assert payload["publication_version"] == 1
    assert len(payload["digest"]) == 64

    # Entities: full contract surface per entry, ordered by external key.
    assert [e["external_key"] for e in payload["entities"]] == [ENTITY_A1, ENTITY_A2]
    first = payload["entities"][0]
    assert set(first) == {"kind", "external_key", "body", "tier", "sensitivity", "attrs"}
    assert first["kind"] == "company"
    assert first["body"] == A_BODY_1
    assert first["tier"] == "raw"                    # authoring-created tier
    assert first["sensitivity"] == "public"          # mirrored from tags
    assert first["attrs"] == {"legacy_id": "c1-legacy"}
    bare_entry = payload["entities"][1]
    assert bare_entry["sensitivity"] is None         # absent tags -> null
    assert bare_entry["attrs"] == {}

    # Relationships: the authoring key convention + structured endpoints.
    assert [rel["external_key"] for rel in payload["relationships"]] == [REL_KEY]
    rel = payload["relationships"][0]
    assert rel["kind"] == "belongs_to"
    assert rel["body"] == REL_BODY
    assert rel["external_key"] == f"{ENTITY_A1}->belongs_to:{ENTITY_A2}"
    assert rel["attrs"]["from"] == ENTITY_A1 and rel["attrs"]["to"] == ENTITY_A2
    assert rel["attrs"]["from_key"] == ENTITY_A1 and rel["attrs"]["to_key"] == ENTITY_A2
    assert rel["from_key"] == ENTITY_A1 and rel["to_key"] == ENTITY_A2

    # First publication: the initial inventory changelog.
    assert payload["changelog"] == {
        "initial": True, "counts": {"entities": 2, "relationships": 1},
    }


def test_pull_yaml_roundtrips_to_the_same_digest(seeded_db):
    """yaml 双格式: ?format=yaml serves application/x-yaml and safe_loads back
    to the same tree — same digest, same version, same keys — as the json."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        token = _register_consumer(admin, "wire", A_KEY)

    with _bare_client(seeded_db) as bare:
        as_json = _pull(bare, A_KEY, token=token)
        as_yaml = _pull(bare, A_KEY, token=token, format="yaml")
    assert as_json.status_code == 200 and as_yaml.status_code == 200
    assert as_yaml.headers["content-type"].startswith("application/x-yaml")

    data = yaml.safe_load(as_yaml.text)
    assert data["digest"] == as_json.json()["digest"]
    assert data["publication_version"] == as_json.json()["publication_version"]
    assert set(data) == set(as_json.json())
    assert [e["external_key"] for e in data["entities"]] == [ENTITY_A1, ENTITY_A2]
    assert data["relationships"][0]["external_key"] == REL_KEY


def test_pull_unknown_format_is_422_naming_allowed_values(seeded_db):
    """非法 format 422: the error names the allowed values json/yaml."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        token = _register_consumer(admin, "wire", A_KEY)

    with _bare_client(seeded_db) as bare:
        r = _pull(bare, A_KEY, token=token, format="xml")
    assert r.status_code == 422
    assert "json" in r.json()["detail"] and "yaml" in r.json()["detail"]


def test_pull_pins_history_version_byte_identical(seeded_db):
    """指定历史版本: after v2 exists, ?version=1 serves v1's frozen snapshot —
    digest equal to the v1 publish-time digest (the flash's 12-hex prefix),
    byte-identical text to the v1 pull taken while v1 was latest, with v1's
    body intact — while the default pull serves v2 whose changelog carries
    the field-level body edit."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        token = _register_consumer(admin, "wire", A_KEY)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        v1_flash = _publish(lara, A_KEY)

    with _bare_client(seeded_db) as bare:
        v1_then = _pull(bare, A_KEY, token=token)
    assert v1_then.status_code == 200
    digest_v1 = v1_then.json()["digest"]
    # The publish flash carried the same content anchor: "v1 · digest <12hex>".
    assert v1_flash["detail"].startswith("v1 · digest ")
    assert digest_v1.startswith(v1_flash["detail"].rsplit("digest ", 1)[1])

    # The edit: alice rewrites alpha-corp's body (everything else identical).
    bench_authoring.authoring_update_unit(
        seeded_db, domain_key=A_KEY, kind="company", external_key=ENTITY_A1,
        body=A_BODY_1_EDITED, operator="alice",
        tags={"status": "draft", "sensitivity": "public"},
        attrs={"legacy_id": "c1-legacy"},
    )
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)  # v2

    with _bare_client(seeded_db) as bare:
        latest = _pull(bare, A_KEY, token=token)
        assert latest.status_code == 200
        v2 = latest.json()
        assert v2["publication_version"] == 2
        assert v2["digest"] != digest_v1  # content changed -> new anchor
        changelog = v2["changelog"]
        assert changelog["added"] == [] and changelog["removed"] == []
        assert [c["key"] for c in changelog["changed"]] == [ENTITY_A1]
        changed_fields = changelog["changed"][0]["fields"]
        assert set(changed_fields) == {"body"}  # field-level, nothing else moved
        assert changed_fields["body"] == {"before": A_BODY_1, "after": A_BODY_1_EDITED}

        # History pin: v1 unchanged, byte-identical to its earlier pull.
        v1_again = _pull(bare, A_KEY, token=token, version=1)
    assert v1_again.status_code == 200
    assert v1_again.text == v1_then.text  # frozen snapshot, immutable across pulls
    assert v1_again.json()["digest"] == digest_v1
    assert v1_again.json()["publication_version"] == 1
    bodies = {e["external_key"]: e["body"] for e in v1_again.json()["entities"]}
    assert bodies[ENTITY_A1] == A_BODY_1  # the edit never rewrote history

    # A version that was never published is an honest 404 naming the version.
    with _bare_client(seeded_db) as bare:
        missing = _pull(bare, A_KEY, token=token, version=99)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "该域无版本 v99"


def test_pull_needs_no_session_no_cookies_at_all(seeded_db):
    """零会话机器面: the pull succeeds with a literally empty cookie jar and
    never touches a Logto session — the only cookie on the wire is the
    app-wide locale preference (set on EVERY response, /healthz included),
    never the auth session cookie — and the SAME bare client is 401'd on the
    Logto-side admin page, proving the pull works because the path is
    auth-exempt (not because auth was disabled)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        token = _register_consumer(admin, "wire", A_KEY)

    with _bare_client(seeded_db) as bare:
        assert dict(bare.cookies) == {}  # nothing was ever signed in
        r = _pull(bare, A_KEY, token=token)
        assert r.status_code == 200
        assert r.json()["domain"] == A_KEY
        # The route reads no cookie and persists no session: of the cookies
        # set app-wide, none is the auth session (the pull face is Logto-free).
        cookie_names = {
            v.split("=", 1)[0]
            for k, v in r.headers.multi_items() if k.lower() == "set-cookie"
        }
        assert AUTH_COOKIE_NAME not in cookie_names

        # Contrast: the same credential-free client on the Logto-side surface.
        denied = bare.get("/admin/distribution")
    assert denied.status_code == 401
    assert denied.json()["detail"] == "not authenticated"


# =========================================================================== #
# 发布动作 RBAC (two-gate: content:write scope + require_domain_role("lead"))   #
# =========================================================================== #


def test_lead_publish_success_flash_and_single_row(seeded_db):
    """lead 发布成功: lara's POST 303s with the version+digest flash, the
    followed page renders it, and exactly one publication row is stamped
    with the operator."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        r = lara.post(
            f"/admin/domains/{A_KEY}/publish", data={}, follow_redirects=True
        )
    assert r.status_code == 200  # back on the domain detail page
    assert "发布完成" in r.text
    assert "v1 · digest" in r.text  # version + digest prefix in the flash

    rows = seeded_db.execute(
        "SELECT version, digest, published_by FROM ontology_publications"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["version"] == 1
    assert len(rows[0]["digest"]) == 64
    assert rows[0]["published_by"] == "lara@example.com"


def test_publish_denied_for_expert_nonmember_and_foreign_lead(seeded_db):
    """两道门: the domain-role gate refuses an expert (below lead), a
    non-member, and the lead of ANOTHER domain — all 403 无该域权限, and no
    publication row is ever created."""
    _seed_world(seeded_db)
    for sub in ("alice", "nobody", "mark"):  # expert / non-member / B's lead
        with _client(seeded_db, _user(sub, _READ_WRITE)) as c:
            r = c.post(
                f"/admin/domains/{A_KEY}/publish", data={}, follow_redirects=False
            )
        assert r.status_code == 403, sub
        assert r.json()["detail"] == "无该域权限"

    assert seeded_db.execute(
        "SELECT count(*) AS n FROM ontology_publications"
    ).fetchone()["n"] == 0


def test_republish_without_change_is_idempotent(seeded_db):
    """幂等重发: a second publish with zero content change flashes the
    idempotent variant naming the SAME version, and the publications table
    still holds one row — one digest, frozen once."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        first = _publish(lara, A_KEY)
        second = _publish(lara, A_KEY, expect="flash.published_idempotent")
    assert second["detail"] == "v1"  # same version, no new snapshot

    rows = seeded_db.execute(
        "SELECT version, digest FROM ontology_publications"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["digest"].startswith(
        first["detail"].rsplit("digest ", 1)[1]
    )  # digest-stability: same content anchor as the first publish


def test_soft_deleted_unit_excluded_from_new_version(seeded_db):
    """软删排除: a unit deleted after v1 leaves the manifest in v2 — the new
    snapshot lacks it entirely and the changelog records it as removed."""
    _seed_world(seeded_db)
    bench_authoring.authoring_create_unit(
        seeded_db, domain_key=A_KEY, kind="company", external_key="delta-corp",
        body="待删除实体正文", operator="alice",
    )
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)  # v1: 3 entities
    bench_authoring.authoring_delete_unit(
        seeded_db, domain_key=A_KEY, kind="company",
        external_key="delta-corp", operator="lara",
    )
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)  # v2
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        token = _register_consumer(admin, "wire", A_KEY)

    with _bare_client(seeded_db) as bare:
        r = _pull(bare, A_KEY, token=token)
    assert r.status_code == 200
    payload = r.json()
    assert payload["publication_version"] == 2
    assert [e["external_key"] for e in payload["entities"]] == [ENTITY_A1, ENTITY_A2]
    # The frozen manifest carries no trace of it (the changelog's `removed`
    # key list is the one legitimate mention).
    assert "delta-corp" not in json.dumps(payload["entities"])
    assert "待删除实体正文" not in r.text
    assert payload["changelog"]["removed"] == ["delta-corp"]
    assert payload["changelog"]["counts"]["entities"] == 2


# =========================================================================== #
# 消费者管理 via HTTP (admin registry: register / revoke / rebind)              #
# =========================================================================== #


def test_register_consumer_token_shown_once_hash_only_persisted(seeded_db):
    """登记与一次性明文: the token rides the creation flash exactly once, the
    DB stores only sha256(token), and no later page render repeats it."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        r = admin.post(
            "/admin/distribution/consumers",
            data={"name": "wire", "domains": A_KEY},
            follow_redirects=False,
        )
        assert r.status_code == 303
        params = _params(r.headers["location"])
        assert params["msg"] == "flash.consumer_registered"
        token = params["detail"]
        assert r.headers["location"].count(token) == 1  # the one disclosure

        # The flash TARGET renders the token once (the flash banner itself)…
        landed = admin.get(r.headers["location"])
        assert landed.status_code == 200
        assert landed.text.count(token) == 1

        # …and the next clean render of the registry page never repeats it.
        after = admin.get("/admin/distribution")
        assert after.status_code == 200
        assert token not in after.text

    row = seeded_db.execute(
        "SELECT name, domains, token_hash, created_by, revoked_at "
        "FROM distribution_consumers WHERE name = %s",
        ("wire",),
    ).fetchone()
    assert row is not None
    assert row["token_hash"] == _digest(token)   # sha256 stored
    assert row["token_hash"] != token            # plaintext never persisted
    assert row["revoked_at"] is None
    assert list(row["domains"]) == [A_KEY]
    assert row["created_by"] == "admin-u@example.com"  # operator stamped


def test_revoke_immediately_kills_pull(seeded_db):
    """吊销即时失效: a working token pulls 200, then one revoke POST later the
    same token is 403 令牌已吊销 — and the row carries revoked_at."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        token = _register_consumer(admin, "wire", A_KEY)

    with _bare_client(seeded_db) as bare:
        assert _pull(bare, A_KEY, token=token).status_code == 200

    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        r = admin.post(
            "/admin/distribution/consumers/wire/revoke",
            data={}, follow_redirects=False,
        )
        assert r.status_code == 303
        assert _params(r.headers["location"])["msg"] == "flash.consumer_revoked"

    assert seeded_db.execute(
        "SELECT revoked_at FROM distribution_consumers WHERE name = %s", ("wire",)
    ).fetchone()["revoked_at"] is not None

    with _bare_client(seeded_db) as bare:
        denied = _pull(bare, A_KEY, token=token)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "令牌已吊销"


def test_set_domains_replaces_binding_wholesale(seeded_db):
    """绑定整体替换: rebinding [A]->[B] is a whole-set swap — A pulls turn
    403 越域 immediately, B pulls turn 200 (the flash names the new set)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        _publish(admin, B_KEY)  # admin bypasses the domain-role gate
        token = _register_consumer(admin, "wire", A_KEY)

    with _bare_client(seeded_db) as bare:
        assert _pull(bare, A_KEY, token=token).status_code == 200

    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        r = admin.post(
            "/admin/distribution/consumers/wire/domains",
            data={"domains": B_KEY}, follow_redirects=False,
        )
        assert r.status_code == 303
        params = _params(r.headers["location"])
        assert params["msg"] == "flash.consumer_domains_set"
        assert params["detail"] == B_KEY

    with _bare_client(seeded_db) as bare:
        out_of_scope = _pull(bare, A_KEY, token=token)
        assert out_of_scope.status_code == 403
        assert out_of_scope.json()["detail"] == "该域不在绑定范围"

        now_allowed = _pull(bare, B_KEY, token=token)
    assert now_allowed.status_code == 200
    assert now_allowed.json()["domain"] == B_KEY
    assert [e["external_key"] for e in now_allowed.json()["entities"]] == [ENTITY_B1]


def test_the_registry_page_shows_which_rows_are_fleets(seeded_db):
    """种类必须在页面上看得见。

    `machine → fleet` 的原地升级只改 `kind` / `fleet_ref`：不给这一列，运维要确认
    「那支舰队现在算不算登记好了」只能去查 SQL——而本变更拆的正是这种静默态。
    """
    _seed_world(seeded_db)
    seeded_db.execute(
        "INSERT INTO distribution_consumers (name, domains, token_hash, created_by, kind, fleet_ref) "
        "VALUES ('win-fleet', '{}', %s, 'seed', 'fleet', 'fleet_1794335712751_wfa3ww')",
        (_digest("fleet-token"),),
    )
    seeded_db.commit()

    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        page = admin.get("/admin/distribution?lang=zh")
        assert page.status_code == 200
        assert "种类" in page.text                    # 表头
        assert "舰队" in page.text and "机器" in page.text
        assert "fleet_1794335712751_wfa3ww" in page.text   # fleet_ref 本身也显示
        # 机器档那行不该凭空长出舰队标识。
        assert page.text.count("fleet_1794335712751_wfa3ww") == 1


def test_non_admin_is_403_on_consumer_registry(seeded_db):
    """admin 专属: a content-scoped user is refused on the registry page AND
    on the register POST (missing scope: admin — platform gate first)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get("/admin/distribution")
        assert page.status_code == 403
        assert page.json()["detail"] == "missing scope: admin"

        post = c.post(
            "/admin/distribution/consumers",
            data={"name": "sneaky", "domains": A_KEY},
            follow_redirects=False,
        )
        assert post.status_code == 403
        assert post.json()["detail"] == "missing scope: admin"

    assert seeded_db.execute(
        "SELECT count(*) AS n FROM distribution_consumers"
    ).fetchone()["n"] == 0


# =========================================================================== #
# payload 不变量 sweep — 错误响应零内容                                         #
# =========================================================================== #


def test_error_responses_never_carry_payload_content(seeded_db):
    """零泄漏 sweep: every pull-face error response (401 / 403 unregistered /
    403 revoked / 403 out-of-scope / 403 unknown domain / 404 no publication /
    404 unknown version) carries neither domain's entity keys, relationship
    keys, bodies, attrs — nor any consumer's plaintext token."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lara:
        _publish(lara, A_KEY)  # only A is published; B has content but no release
    with _client(seeded_db, _user("admin-u", ["*"])) as admin:
        wire = _register_consumer(admin, "wire", f"{A_KEY},{B_KEY}")
        peeker = _register_consumer(admin, "peeker", B_KEY)
        doomed = _register_consumer(admin, "doomed", A_KEY)
        admin.post(
            "/admin/distribution/consumers/doomed/revoke",
            data={}, follow_redirects=False,
        )

    with _bare_client(seeded_db) as bare:
        positive = _pull(bare, A_KEY, token=wire)
        assert positive.status_code == 200  # positive control: content exists

        responses = {
            "401-missing": _pull(bare, A_KEY),
            "403-unregistered": _pull(bare, A_KEY, token="garbage-token"),
            "403-revoked": _pull(bare, A_KEY, token=doomed),
            "403-out-of-scope": _pull(bare, A_KEY, token=peeker),
            "403-unknown-domain": _pull(bare, "ghost-key", token=wire),
            "404-no-publication": _pull(bare, B_KEY, token=wire),
            "404-unknown-version": _pull(bare, A_KEY, token=wire, version=9),
        }

    expected_status = {
        "401-missing": 401,
        "403-unregistered": 403,
        "403-revoked": 403,
        "403-out-of-scope": 403,
        "403-unknown-domain": 403,
        "404-no-publication": 404,
        "404-unknown-version": 404,
    }
    for label, response in responses.items():
        assert response.status_code == expected_status[label], label
        for fragment in _A_CONTENT + _B_CONTENT:
            assert fragment not in response.text, (label, fragment)
        for plaintext in (wire, peeker, doomed):
            assert plaintext not in response.text, (label, "token leak")
