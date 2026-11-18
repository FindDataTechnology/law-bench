"""Tests for the anonymous public overview tier (add-bench-public-overview-tier).

The overview is the ONE app-level exempt path on the public pod. These tests
exercise the REAL ``get_current_user`` (no override) so the narrow-exemption
posture is actually under test:

- anonymous overview 200 with the payload contract (and no corpus content);
- digest/published_at match the distribution kernel's own records;
- exemption does not leak to sibling paths (401, not 404) and does not exist
  on the origin (route unmounted -> 404);
- a broken/unset exemption registration fail-closes to 401;
- rate limiting applies to anonymous and keyed callers alike (429);
- DB failure degrades to 503 with an exception-class reason and as_of stays
  anchored to the data (published_at), never the server clock.

Seeding uses the real kernel chain (templates -> workspaces -> authoring ->
distribution.publish_domain) so the overview reads exactly what consumers pull.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from psycopg import OperationalError

from src.bench import authoring, distribution, templates, workspaces
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.auth import apikey
from src.web.deps import get_db
from src.web.public_app import create_public_app
from src.web.rate_limit import TokenBucketLimiter, add_rate_limit_middleware
from src.web.routes.public_overview import OVERVIEW_PATH


@pytest.fixture
def public_client(seeded_db) -> TestClient:
    """Public app with the REAL get_current_user; get_db -> seeded session DB."""
    app = create_public_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        yield client


def _seed_published_domain(conn, domain_key: str) -> dict:
    """One template + domain with 2 entities + 1 relationship, published v1.

    Mirrors tests/test_distribution_kernel.py's seeding (authoring gate reads
    entity_types/relationship_kinds from the template schema).
    """
    from src.bench.promotion import SENSITIVITY_LEVELS

    schema = {
        "entity_types": ["company", "indicator"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    tmpl = templates.create_template(
        conn, name=f"tpl-{domain_key}", schema=schema, created_by="admin-1"
    )
    workspaces.instantiate_domain(
        conn,
        key=domain_key,
        name=f"Domain {domain_key}",
        template_name=f"tpl-{domain_key}",
        template_version=tmpl["version"],
        created_by="admin-1",
    )
    authoring.authoring_create_unit(
        conn, domain_key=domain_key, kind="company",
        external_key="co-1", body="公司一", operator="expert-1",
    )
    authoring.authoring_create_unit(
        conn, domain_key=domain_key, kind="company",
        external_key="co-2", body="公司二", operator="expert-1",
    )
    authoring.authoring_create_relationship(
        conn, domain_key=domain_key, kind="belongs_to",
        from_key="co-1", to_key="co-2", body="归属", operator="expert-1",
    )
    return distribution.publish_domain(conn, domain_key=domain_key, published_by="lead-1")


# --- anonymous 200 + payload contract --------------------------------------- #


def test_overview_anonymous_200_empty(public_client: TestClient):
    """No publications -> 200 with empty versions, zeroed totals, as_of null."""
    r = public_client.get(OVERVIEW_PATH)
    assert r.status_code == 200
    body = r.json()
    assert body["ontology_versions"] == []
    assert body["as_of"] is None
    assert body["totals"]["domains"] == 0
    assert body["totals"]["entities"] == 0


def test_overview_anonymous_200_payload_contract(public_client: TestClient, seeded_db):
    """Published domain -> version row with digest/counts; digest matches the
    kernel's own record; corpus bodies never appear."""
    pub = _seed_published_domain(seeded_db, "legal")

    r = public_client.get(OVERVIEW_PATH)
    assert r.status_code == 200
    body = r.json()
    assert len(body["ontology_versions"]) == 1
    v = body["ontology_versions"][0]
    assert v["domain_key"] == "legal"
    assert v["version"] == pub["version"]
    assert v["digest"] == pub["digest"]
    # digest/anchored published_at agree with the distribution pull surface
    latest = distribution.get_publication(seeded_db, domain_key="legal")
    assert v["digest"] == latest["digest"]
    assert v["published_at"] == latest["published_at"]
    counts = v["counts"]
    assert counts["entities"] == 2
    assert counts["relations"] == 1
    assert sum(counts["by_tier"].values()) == 3
    # as_of anchored to the DATA's publish time, not the server clock
    assert body["as_of"] == latest["published_at"]
    # corpus content and internal identifiers never cross the boundary
    assert "公司一" not in r.text
    assert "公司二" not in r.text
    assert "归属" not in r.text
    assert "published_by" not in body
    assert "changelog" not in body
    assert "manifest" not in body
    assert "lead-1" not in r.text
    assert body["totals"]["domains"] == 1
    assert body["totals"]["entities"] == 2


def test_overview_as_of_is_data_time_not_clock(public_client: TestClient, seeded_db):
    """A publication from an earlier instant must not look fresh: as_of equals
    the stored published_at even though 'now' is later."""
    _seed_published_domain(seeded_db, "legal")
    latest = distribution.get_publication(seeded_db, domain_key="legal")
    r = public_client.get(OVERVIEW_PATH)
    body = r.json()
    assert body["as_of"] == latest["published_at"]
    assert body["as_of"] is not None


# --- exemption does not leak ------------------------------------------------- #


def test_sibling_paths_anonymous_401(public_client: TestClient):
    """The exemption is exact-path only: siblings under /api/public/ get 401
    (auth runs via the authenticated catch-all) instead of a route-less 404."""
    for path in ("/api/public/overview/x", "/api/public/other", "/api/public/"):
        r = public_client.get(path)
        assert r.status_code == 401, path
    r = public_client.post("/api/public/overview/x")
    assert r.status_code == 401


def test_sibling_paths_keyed_404(public_client: TestClient):
    """A valid key passes auth on a sibling but nothing is served there: 404."""
    plaintext = apikey.create_key("api-user", "overview-test", ["*"])
    r = public_client.get(
        "/api/public/overview/x", headers={"X-API-Key": plaintext}
    )
    assert r.status_code == 404


def test_existing_protected_routes_still_401(public_client: TestClient):
    """The exemption changed nothing for the previously-protected surface."""
    r = public_client.get("/api/contracts/sale")
    assert r.status_code == 401
    r = public_client.get("/samples")
    assert r.status_code == 401


def test_healthz_still_open(public_client: TestClient):
    """The classic exemption is untouched."""
    r = public_client.get("/healthz")
    assert r.status_code == 200


def test_origin_app_anonymous_unreachable(seeded_db, monkeypatch):
    """The origin workbench neither mounts the overview nor registers the
    exemption: the path is unregistered there (404 for ANY caller — anonymous
    or keyed). Fail-closed by absence: no anonymous face exists on the origin."""
    monkeypatch.setattr("src.web.app.logto.verify_reachable", lambda: None)
    from src.web.app import create_app

    app = create_app()
    assert not hasattr(app.state, "extra_exempt_paths")
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        r = client.get(OVERVIEW_PATH)
        assert r.status_code == 404
        plaintext = apikey.create_key("api-user", "origin-absent-test", ["*"])
        r_keyed = client.get(OVERVIEW_PATH, headers={"X-API-Key": plaintext})
        assert r_keyed.status_code == 404


# --- fail-closed posture ------------------------------------------------------ #


def test_missing_exemption_registration_fails_closed(seeded_db):
    """An app whose factory did not register the exemption -> anonymous 401."""
    app = create_public_app()
    del app.state.extra_exempt_paths  # simulate a factory that opted out
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        r = client.get(OVERVIEW_PATH)
        assert r.status_code == 401


def test_unusable_exemption_value_fails_closed(seeded_db):
    """A non-set extra_exempt_paths value fail-closes (never opens)."""
    app = create_public_app()
    app.state.extra_exempt_paths = "not-a-set"
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        r = client.get(OVERVIEW_PATH)
        assert r.status_code == 401


# --- honest degradation -------------------------------------------------------- #


class _BrokenConn:
    """A DB connection whose reads raise (simulates a dead replica)."""

    def execute(self, *args, **kwargs):
        raise OperationalError("simulated replica outage")

    def commit(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_db_failure_503_with_class_reason(seeded_db):
    """DB unreachable -> 503 {error, reason}; no stale snapshot, no internals."""
    app = create_public_app()
    app.dependency_overrides[get_db] = lambda: _BrokenConn()
    with TestClient(app) as client:
        r = client.get(OVERVIEW_PATH)
        assert r.status_code == 503
        body = r.json()
        assert body["error"] == "overview unavailable"
        assert body["reason"] == "OperationalError"
        # no DSN/host internals in the reason
        assert "simulated" not in body["reason"]
        assert ":" not in body["reason"]


# --- rate limiting (public pod posture: enabled) ------------------------------- #


def test_anonymous_overview_rate_limited(seeded_db):
    """Anonymous callers are throttled: burst=1 -> second request 429 with
    Retry-After, whatever the auth outcome would have been."""
    app = create_public_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    add_rate_limit_middleware(app, limiter=TokenBucketLimiter(rps=0.001, burst=1))
    with TestClient(app) as client:
        first = client.get(OVERVIEW_PATH)
        assert first.status_code == 200
        second = client.get(OVERVIEW_PATH)
        assert second.status_code == 429
        assert "Retry-After" in second.headers


def test_keyed_overview_rate_limited(seeded_db):
    """A valid key is NOT exempt from throttling: keyed caller over limit -> 429."""
    plaintext = apikey.create_key("api-user", "overview-rate-test", ["*"])
    app = create_public_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    add_rate_limit_middleware(app, limiter=TokenBucketLimiter(rps=0.001, burst=1))
    with TestClient(app) as client:
        headers = {"X-API-Key": plaintext}
        assert client.get(OVERVIEW_PATH, headers=headers).status_code == 200
        again = client.get(OVERVIEW_PATH, headers=headers)
        assert again.status_code == 429
        assert "Retry-After" in again.headers
