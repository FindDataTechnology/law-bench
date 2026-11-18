"""Logto permission scopes -> what authorization actually checks.

Authorization in the workbench is expressed as *scopes* — every managed route is
gated by :func:`src.web.auth.deps.require_scope`. The scopes come straight from
the ``scope`` claim of the Logto **access token** minted for the configured API
Resource (``LOGTO_API_RESOURCE``): roles in Logto are permission bundles, and the
token's ``scope`` claim is the union of the permissions those roles grant. The
app therefore keeps **no role table** — the Logto console is the single source of
truth, and changing a role's powers is a console edit with no redeploy.

The permission vocabulary is the API Resource's scope set: ``content:read``,
``content:write``, and ``admin``. The ``admin`` permission is normalized to also
carry the ``"*"`` wildcard so one admin grant satisfies every check (including a
route that starts requiring a new scope later). Absence of a recognized scope
grants nothing — fail closed.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.settings import admitted_scope_set

#: The recognized scope vocabulary of the API Resource. Used only to normalize
#: the ``admin`` permission into the ``"*"`` wildcard; authorization itself is a
#: plain membership check against whatever the token grants.
ADMIN_SCOPE = "admin"
WILDCARD_SCOPE = "*"


def scopes_from_claims(claims: dict) -> list[str]:
    """Parse a token's ``scope`` claim into the app's effective scope list.

    Logto emits ``scope`` as a space-delimited string on an access token; a list
    or other sequence is also accepted defensively. A missing or wrong-typed
    claim yields ``[]`` (which the admission gate treats as denied). The
    ``admin`` permission is expanded to also include the ``"*"`` wildcard.

    Order-preserving and de-duplicated so the result is stable across calls
    (readable in logs and deterministic in tests).
    """
    raw = claims.get("scope")
    if isinstance(raw, str):
        scopes = [part for part in raw.split() if part]
    elif isinstance(raw, (list, tuple, set, frozenset)):
        scopes = [str(part) for part in raw if part]
    else:
        scopes = []

    if ADMIN_SCOPE in scopes and WILDCARD_SCOPE not in scopes:
        scopes.append(WILDCARD_SCOPE)
    return scopes


def is_admitted(scopes: Iterable[str]) -> bool:
    """True iff ``scopes`` intersects the admitted-scope set (fail closed)."""
    return bool(set(scopes) & admitted_scope_set())
