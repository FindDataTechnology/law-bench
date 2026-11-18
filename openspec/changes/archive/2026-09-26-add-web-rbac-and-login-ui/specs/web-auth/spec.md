## MODIFIED Requirements

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

### Requirement: Logto configuration via environment

The system SHALL read all Logto integration parameters from environment variables: `LOGTO_ENDPOINT` (issuer base URL), `LOGTO_CLIENT_ID`, `LOGTO_CLIENT_SECRET`, `LOGTO_REDIRECT_URI`, `LOGTO_API_RESOURCE` (the API Resource indicator the app requests and audience-checks access tokens against), and `AUTH_SESSION_SECRET`. The application MUST fail fast at startup if any required variable is missing or if JWKS cannot be fetched, rather than running an open or partially-open server.

#### Scenario: Missing required auth env at startup
- **WHEN** the application starts with `LOGTO_ENDPOINT` or `LOGTO_CLIENT_ID` or `AUTH_SESSION_SECRET` unset
- **THEN** startup aborts with a `ConfigError` naming the missing variable before binding any port

#### Scenario: JWKS unreachable at startup
- **WHEN** `LOGTO_ENDPOINT` is set but the JWKS document cannot be fetched during startup
- **THEN** startup aborts with an error indicating JWKS fetch failure

## ADDED Requirements

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
