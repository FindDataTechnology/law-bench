# spec — web-auth (delta)

## MODIFIED Requirements

### Requirement: Unified identity resolution via get_current_user

The system SHALL resolve the caller's identity through exactly one FastAPI dependency, `get_current_user`, which MUST attempt, in order: (1) a valid signed session cookie, (2) an `Authorization: Bearer <jwt>` header validated against Logto's JWKS, (3) an `X-API-Key` header validated against the `api_keys` table. The first method that succeeds SHALL establish the identity; the dependency MUST short-circuit and not fall through to a weaker method after a present-but-invalid credential. The resolved identity MUST be attached to `request.state.user` for downstream handlers and to FastAPI's `Request.user` for route logic.

When the `X-API-Key` channel succeeds, the verify path SHALL touch the key's `last_used_at` column. This touch SHALL be best-effort: if the write cannot persist (because the service is running against a read-only Postgres read-replica, as the public pod does), the touch SHALL be skipped and the request SHALL still succeed — a non-persisting `last_used_at` write MUST NOT cause `401` or `500`. On the origin (writable primary) the touch SHALL persist as before. The present-but-invalid-credential binding and the cookie→Bearer→API-Key order are unchanged on both the origin and the public pod.

#### Scenario: Valid session cookie authenticates the request

- **WHEN** a request carries a valid, non-expired signed session cookie and no other credential
- **THEN** `get_current_user` resolves the identity from the cookie and the request proceeds without `401`

#### Scenario: Valid Bearer JWT authenticates the request

- **WHEN** a request carries `Authorization: Bearer <jwt>` where the JWT is signed by Logto's current signing key and unexpired, and no session cookie is present
- **THEN** `get_current_user` resolves the identity from the JWT and the request proceeds

#### Scenario: Valid API key authenticates the request

- **WHEN** a request carries `X-API-Key: <key>` whose hash matches an active row in `api_keys`, and no cookie or Bearer token is present
- **THEN** `get_current_user` resolves the identity from the API key and the request proceeds

#### Scenario: Present-but-invalid credential does not fall through

- **WHEN** a request carries a Bearer JWT that fails JWKS validation (bad signature / expired) and also a valid `X-API-Key`
- **THEN** the system responds `401` rather than silently using the API key — a presented credential is binding, not advisory

#### Scenario: last_used_at touch is best-effort on a read replica

- **WHEN** a request carries a valid `X-API-Key` and the service is running against a read-only Postgres replica (the public pod), so the `UPDATE api_keys SET last_used_at = ...` write cannot persist
- **THEN** the identity is still resolved from the key, the request proceeds without `401` or `500`, and the failed touch is logged at most once (not per-request noise)

#### Scenario: last_used_at touch persists on the origin primary

- **WHEN** a request carries a valid `X-API-Key` and the service is running against the writable origin Postgres primary
- **THEN** the `last_used_at` column is updated for that key, as before this change
