## Purpose

Permission-scoped access control for the law-bench workbench: which identities may sign in
and what each may do. It follows Logto's RBAC model — a Logto API Resource carries the
permission scopes, Logto roles bundle those permissions, and the app authorizes solely on
the scopes the access token grants. It covers the admission gate, per-route enforcement,
permission-aware navigation, and the fail-closed posture that lets business/content staff
(业务人员) manage backend content without granting them full administrative control.

## ADDED Requirements

### Requirement: Permission-scoped authorization model

The system SHALL obtain each authenticated identity's authorization scopes from the `scope`
claim of the Logto **access token** minted for the configured API Resource
(`LOGTO_API_RESOURCE`), and SHALL express every authorization decision as a check against
those scopes. The scope vocabulary is the Logto permission set for the API Resource:
`content:read`, `content:write`, and `admin`. The `admin` permission SHALL be treated as the
wildcard scope; `content:write` SHALL permit creating and modifying backend content but not
the administrative scope; `content:read` SHALL permit reading only. The system SHALL NOT
maintain its own role-to-scope table: roles are permission bundles that exist only in
Logto, and changing a role's powers is a Logto-console operation that requires no code
redeploy.

#### Scenario: Scopes are read from the access token

- **WHEN** an identity signs in and its Logto roles grant the API-Resource permissions
  `content:read` and `content:write`
- **THEN** the resolved identity reports exactly those granted scopes and no others

#### Scenario: Permission maps to the expected scopes

- **WHEN** an identity's roles grant the `admin` permission
- **THEN** it is treated as holding the wildcard scope
- **AND** when an identity's roles grant only `content:read`, it holds the read scope and
  neither the mutation nor the administrative scope

### Requirement: Login admission gate

Only identities whose access token carries at least one admitted permission scope SHALL be
granted a workbench session. `GET /auth/callback` SHALL evaluate the token's `scope` set
against the admitted-scope set and, for an identity holding none of them, MUST NOT issue a
session cookie and MUST respond with a login-denied page (HTTP `403`) that states, in the
active locale, that access requires an assigned permission.

#### Scenario: Admitted scope completes login

- **WHEN** a user whose token carries an admitted scope completes the OIDC callback
- **THEN** the system sets the session cookie and redirects into the workbench

#### Scenario: Identity without an admitted scope is denied

- **WHEN** a user authenticates successfully at the IdP but the token carries none of the
  admitted scopes
- **THEN** the system responds `403` with a login-denied page, sets no session cookie, and
  the user cannot reach any workbench route

#### Scenario: Missing scope claim is denied

- **WHEN** the IdP returns a valid token carrying no `scope` claim at all
- **THEN** the identity is treated as holding no admitted scope and is denied with `403`

### Requirement: Per-route scope enforcement

Routes that manage backend content SHALL require the corresponding scope, enforced through
the existing `require_scope()` dependency. A request with no valid credential SHALL receive
`401`; an authenticated identity lacking the required scope SHALL receive `403`. The scope
check SHALL apply uniformly across the cookie, Bearer, and API-key channels: an identity
authorized by an API key MUST satisfy the same scope requirement as one authorized by a
cookie.

#### Scenario: Editor may mutate content

- **WHEN** an identity holding the `content:write` scope calls a content-mutating route
- **THEN** the route executes and returns its normal success response

#### Scenario: Viewer is forbidden from mutating content

- **WHEN** an identity holding only `content:read` calls a content-mutating route
- **THEN** the system responds `403` and does not perform the mutation

#### Scenario: Admin is permitted on administrative routes

- **WHEN** an identity holding the `admin` (wildcard) scope calls an administrative route
- **THEN** the route executes

### Requirement: Permission-aware navigation

The workbench UI SHALL hide the navigation entries and actions that the current identity is
not permitted to use, and SHALL show them to identities that are permitted. Navigation
filtering SHALL be a usability layer only; it MUST NOT replace server-side enforcement.

#### Scenario: Navigation is filtered for a read-only identity

- **WHEN** an identity holding only `content:read` opens the workbench
- **THEN** navigation entries requiring the `content:write` or `admin` scope are not rendered

#### Scenario: Navigation is complete for an admin

- **WHEN** an identity holding the `admin` scope opens the workbench
- **THEN** all navigation entries the wildcard scope permits are rendered

### Requirement: Fail-closed authorization

Absent, empty, or unrecognized scopes MUST deny access rather than admit it. The system
SHALL NOT treat an unrecognized scope, a missing `scope` claim, or a parse miss as an
implicit grant.

#### Scenario: Unrecognized scope is denied

- **WHEN** an identity's token carries only scopes that are not in the permission vocabulary
- **THEN** it is granted no effective scope and is denied at the admission gate

#### Scenario: Empty scope set is denied

- **WHEN** an identity's scope set is empty
- **THEN** no scope is granted and access is denied
