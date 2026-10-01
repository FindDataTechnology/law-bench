"""Unit tests for the permission-scope model (``src/web/auth/scopes.py``).

Hermetic: no DB, no network, no LLM — this is the pure layer every authorization
decision rests on, so the fail-closed edges (missing claim, empty set, unknown
scope) are asserted explicitly.
"""

from __future__ import annotations

import pytest

from src.web.auth import scopes


def test_space_delimited_scope_claim_is_parsed():
    assert scopes.scopes_from_claims({"scope": "content:read content:write"}) == [
        "content:read",
        "content:write",
    ]


def test_admin_permission_expands_to_wildcard():
    assert scopes.scopes_from_claims({"scope": "content:read admin"}) == [
        "content:read",
        "admin",
        "*",
    ]
    # Idempotent: an explicit wildcard already present is not duplicated.
    assert scopes.scopes_from_claims({"scope": "admin *"}) == ["admin", "*"]


@pytest.mark.parametrize(
    "claims,expected",
    [
        ({"scope": "content:read"}, ["content:read"]),
        ({"scope": ["content:read", "content:write"]}, ["content:read", "content:write"]),
        ({"scope": "  content:read   content:write  "}, ["content:read", "content:write"]),
        ({}, []),
        ({"scope": ""}, []),
        ({"scope": None}, []),
        ({"scope": 7}, []),
        ({"scope": []}, []),
    ],
)
def test_scopes_from_claims_shapes(claims, expected):
    assert scopes.scopes_from_claims(claims) == expected


def test_unknown_scope_is_kept_but_grants_nothing(monkeypatch):
    # Unknown scopes pass through untouched (the token is the source of truth),
    # but they never admit an identity nor satisfy a require_scope check.
    monkeypatch.delenv("AUTH_ADMITTED_SCOPES", raising=False)
    assert scopes.scopes_from_claims({"scope": "root:everything"}) == ["root:everything"]
    assert scopes.is_admitted(["root:everything"]) is False


def test_is_admitted_intersects_the_admitted_set(monkeypatch):
    monkeypatch.delenv("AUTH_ADMITTED_SCOPES", raising=False)  # default set
    assert scopes.is_admitted(["content:read"]) is True
    assert scopes.is_admitted(["content:write"]) is True
    assert scopes.is_admitted(["admin"]) is True
    # A mixed set admits on the strength of one known scope.
    assert scopes.is_admitted(["root:everything", "content:read"]) is True
    # Wildcard alone is not an admitted *name* (it is synthesized from admin,
    # which co-occurs, so a real admin token still admits).
    assert scopes.is_admitted(["*"]) is False
    assert scopes.is_admitted(["other:scope"]) is False
    assert scopes.is_admitted([]) is False

    monkeypatch.setenv("AUTH_ADMITTED_SCOPES", "admin")
    assert scopes.is_admitted(["content:read"]) is False
    assert scopes.is_admitted(["admin"]) is True
    monkeypatch.setenv("AUTH_ADMITTED_SCOPES", "content:read, content:write")
    assert scopes.is_admitted(["content:write"]) is True  # whitespace-trimmed
