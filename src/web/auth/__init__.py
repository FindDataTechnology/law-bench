"""Web-layer authentication (Phase 2 — Logto hybrid Cookie + APIKey).

This package owns identity for the HTTP surface. The app stores NO passwords
and has NO local users table; identity is fully delegated to a self-deployed
Logto instance (OIDC). Three credential channels converge on one
``request.state.user``:

- **Browser** — OIDC authorization-code flow -> signed httpOnly session cookie
  (:mod:`session`).
- **Programmatic Bearer** — Logto-issued JWT validated against the IdP JWKS
  (:mod:`logto`).
- **Programmatic API key** — self-managed ``X-API-Key`` (salted hash in the
  ``api_keys`` table, :mod:`apikey`).

:mod:`deps` resolves a request to a :class:`~deps.User` from any of the three,
failing closed (401) on a present-but-invalid credential with NO fallthrough to
a weaker method.
"""
