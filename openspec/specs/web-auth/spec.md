# web-auth Specification

## Purpose
Enforce authentication across the web surface through one shared dependency: Logto OIDC browser login, signed session cookies, Bearer JWT validation against JWKS, an explicit exemption set, and API key management.

## Requirements
### Requirement: All non-exempt endpoints require authentication

The system SHALL enforce authentication on every HTTP route except the explicit exemption set. The exemption set MUST contain at least the liveness probe (`/healthz`) and the authentication routes themselves (`/auth/*` and `/api/keys` where unauthenticated access is required to start the login flow). Authentication MUST be enforced by applying a single FastAPI dependency (`get_current_user`) to all routers at include time, so a newly added router cannot accidentally be open.

#### Scenario: Unauthenticated request to a protected endpoint is rejected
- **WHEN** a request arrives at any protected route (e.g. `GET /api/rubrics`) with no session cookie, no `Authorization` header, and no `X-API-Key`
- **THEN** the system responds `401 Unauthorized` with a JSON body `{"error": "authentication required"}` and does not execute the route handler

#### Scenario: Liveness probe remains unauthenticated
- **WHEN** a request arrives at `GET /healthz` with no credentials
- **THEN** the system responds `200` with `{"status": "ok"}` without consulting authentication state

#### Scenario: Login routes remain unauthenticated
- **WHEN** an unauthenticated request arrives at `GET /auth/login`
- **THEN** the system initiates the OIDC redirect to Logto rather than returning `401`

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

### Requirement: Browser login via Logto OIDC authorization code flow

The system SHALL implement an OIDC authorization code flow for browser users. `GET /auth/login` MUST redirect to Logto's authorization endpoint with `client_id`, `redirect_uri`, `response_type=code`, `scope=<requested scopes>`, `resource=<LOGTO_API_RESOURCE>`, and a PKCE `code_challenge`/`code_verifier` pair. The `resource` parameter (the registered API Resource indicator) MUST also be sent when exchanging the code at the token endpoint, so the returned **access token** is minted for that resource. `GET /auth/callback` MUST exchange the `code` for tokens, validate the ID token against JWKS for identity, validate the access token against JWKS (with `aud` equal to `LOGTO_API_RESOURCE`), read the access token's `scope` claim as the identity's granted permissions, evaluate the scope-admission gate (per the web-rbac capability), and — only for an identity holding an admitted scope — set an httpOnly, Secure, SameSite=Lax session cookie containing the resolved user identity (including its scopes) before redirecting to the application root. An identity that authenticates successfully but holds no admitted scope MUST receive a `403` login-denied response and MUST NOT receive a session cookie.

#### Scenario: Login redirect to Logto
- **WHEN** an unauthenticated browser user hits `GET /auth/login`
- **THEN** the system responds `302` to Logto's authorization endpoint with a PKCE `code_challenge` and a `resource` parameter for the configured API Resource included

#### Scenario: Callback sets session cookie
- **WHEN** Logto redirects to `GET /auth/callback?code=...&state=...` with a valid authorization code matching the issued state, and the access token's `scope` includes an admitted permission
- **THEN** the system exchanges the code for tokens, validates the ID token and the access token, evaluates the scope-admission gate, sets an httpOnly Secure SameSite=Lax session cookie that includes the identity's scopes, and responds `302` to `/`

#### Scenario: Callback denies an identity without an admitted scope
- **WHEN** `GET /auth/callback` receives a valid code whose access token carries no admitted scope
- **THEN** the system responds `403` with a login-denied page, sets no session cookie, and does not redirect into the workbench

#### Scenario: Invalid callback is rejected
- **WHEN** `GET /auth/callback` is called with no `code`, an unknown `state`, or a code Logto refuses to exchange
- **THEN** the system responds `400` with `{"error": "invalid callback"}` and sets no cookie

### Requirement: Session cookie signing and validation

The system SHALL sign the session cookie with a server-side secret (`AUTH_SESSION_SECRET`) using a tamper-evident mechanism (e.g. `itsdangerous` or `starlette` Session middleware). A cookie whose signature does not validate, or whose payload indicates expiry past a configurable `AUTH_SESSION_TTL`, MUST be treated as absent (not as a `401` error by itself — the caller may still present another credential).

#### Scenario: Tampered cookie is rejected
- **WHEN** a request carries a session cookie whose signature does not validate against `AUTH_SESSION_SECRET`
- **THEN** the cookie is ignored and `get_current_user` proceeds to the next credential method

#### Scenario: Expired session cookie is ignored
- **WHEN** a request carries a session cookie whose `iat`/`exp` indicates it is older than `AUTH_SESSION_TTL`
- **THEN** the cookie is ignored and the caller may authenticate via Bearer or API key

### Requirement: Bearer JWT validation against Logto JWKS

The system SHALL validate `Authorization: Bearer <jwt>` tokens by fetching Logto's JWKS (cached with periodic refresh), matching the `kid` header to a signing key, verifying the signature, confirming the `iss` equals the configured Logto issuer, and checking `exp` is in the future. A token failing any check MUST yield a `401` and MUST NOT fall through to API-key auth.

#### Scenario: JWKS-cached key validates a fresh token
- **WHEN** a Bearer JWT signed by a key present in the cached JWKS is presented and `exp` is valid
- **THEN** the identity is resolved from the JWT claims and the request proceeds

#### Scenario: Expired Bearer token is rejected
- **WHEN** a Bearer JWT has `exp` in the past
- **THEN** the system responds `401` with `{"error": "token expired"}` and does not consult `X-API-Key`

### Requirement: API key management endpoints

The system SHALL expose `POST /api/keys` (create — returns the plaintext key exactly once), `GET /api/keys` (list the caller's keys, never returning plaintext), `DELETE /api/keys/{id}` (revoke). Keys MUST be stored only as a salted hash (`key_hash`); the plaintext MUST NOT be persisted or logged. Each key MUST carry `user_id`, optional `scopes`, `created_at`, and `last_used_at`.

#### Scenario: Create returns plaintext once
- **WHEN** an authenticated user `POST /api/keys` with a label
- **THEN** the system creates an `api_keys` row storing only the salted hash, and returns the plaintext key in the `201` response body exactly once

#### Scenario: List never returns plaintext
- **WHEN** an authenticated user `GET /api/keys`
- **THEN** the response contains `id`, `label`, `scopes`, `created_at`, `last_used_at` for each key and never contains the plaintext or the hash

#### Scenario: Revoke deletes the key
- **WHEN** an authenticated user `DELETE /api/keys/{id}` for a key they own
- **THEN** the row is removed and subsequent requests carrying that key are `401`

#### Scenario: User cannot revoke another user's key
- **WHEN** an authenticated user `DELETE /api/keys/{id}` where the row belongs to a different user
- **THEN** the system responds `404` (not `403`, to avoid leaking existence) and the row is unchanged

### Requirement: Logout clears the session

The system SHALL expose `GET /auth/logout` or `POST /auth/logout` that clears the session cookie and, if Logto's end-session endpoint is configured, redirects there to terminate the Logto SSO session as well.

#### Scenario: Logout clears the cookie
- **WHEN** an authenticated browser user hits `/auth/logout`
- **THEN** the system clears the session cookie (max-age=0) and, if an end-session endpoint is configured, redirects to it; otherwise redirects to `/`

### Requirement: Logto configuration via environment

The system SHALL read all Logto integration parameters from environment variables: `LOGTO_ENDPOINT` (issuer base URL), `LOGTO_CLIENT_ID`, `LOGTO_CLIENT_SECRET`, `LOGTO_REDIRECT_URI`, `LOGTO_API_RESOURCE` (the API Resource indicator the app requests and audience-checks access tokens against), and `AUTH_SESSION_SECRET`. The application MUST fail fast at startup if any required variable is missing or if JWKS cannot be fetched, rather than running an open or partially-open server.

#### Scenario: Missing required auth env at startup
- **WHEN** the application starts with `LOGTO_ENDPOINT` or `LOGTO_CLIENT_ID` or `AUTH_SESSION_SECRET` unset
- **THEN** startup aborts with a `ConfigError` naming the missing variable before binding any port

#### Scenario: JWKS unreachable at startup
- **WHEN** `LOGTO_ENDPOINT` is set but the JWKS document cannot be fetched during startup
- **THEN** startup aborts with an error indicating JWKS fetch failure

### Requirement: Workbench UI reflects authentication state

The workbench SHALL make authentication state visible in its chrome. When the current request is authenticated, the UI SHALL render the current user's display identity (name and/or email) together with a logout affordance that targets the logout route. When the current request is not authenticated, the UI SHALL render a login affordance that targets the login route. The logout affordance SHALL be present on every authenticated page, not only a settings page.

#### Scenario: Authenticated user sees identity and logout

- **WHEN** an authenticated user opens any workbench page
- **THEN** the page chrome displays that user's name and/or email and a logout control that points at `/auth/logout`

#### Scenario: Logout control terminates the session

- **WHEN** an authenticated user activates the logout control
- **THEN** the browser is sent to `/auth/logout`, the session cookie is cleared, and the user is redirected to the IdP end-session endpoint (or `/` when none is configured)
- **AND** the end-session URL identifies the client (`client_id`) so the IdP honours the post-logout redirect and returns the user to the application base URL, rather than a generic IdP end-session page

#### Scenario: Unauthenticated visitor sees a login affordance

- **WHEN** an unauthenticated visitor reaches a page that renders the workbench chrome
- **THEN** the UI renders a login affordance pointing at `/auth/login`
