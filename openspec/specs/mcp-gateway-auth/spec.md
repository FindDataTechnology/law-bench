# mcp-gateway-auth Specification

## Purpose

Authentication and identity behavior for the AI Gateway & Registry deployed at
mcp.token118.com: interactive login, group-based authorization, machine-to-machine API
access, and the public Logto endpoint posture that backs them.

## Requirements

### Requirement: Interactive login via Logto

The gateway SHALL authenticate interactive users through the shared Logto instance using
the OAuth2 authorization-code flow with PKCE, with browser-facing endpoints on
`https://auth.token118.com/oidc/*`.

#### Scenario: Unauthenticated browser is redirected to Logto

- **WHEN** an unauthenticated browser requests a protected page or API route on
  `mcp.token118.com`
- **THEN** the gateway responds with a redirect to the Logto authorization endpoint
  (`https://auth.token118.com/oidc/auth`) carrying a PKCE challenge and signed state
- **AND** after successful login at Logto, the browser returns to the gateway callback
  and receives an authenticated gateway session

#### Scenario: Logout ends the session

- **WHEN** a logged-in user logs out of the gateway
- **THEN** the gateway session is destroyed and the user is redirected to the Logto end
  session endpoint

### Requirement: Fail-closed id_token verification

The gateway SHALL verify the Logto id_token (signature against Logto JWKS, issuer,
audience, expiry, and nonce when the login bound one) before creating any session, and
SHALL deny the login on any verification failure without falling back to unverified
claims.

#### Scenario: Tampered or unverifiable id_token is rejected

- **WHEN** the token exchange returns an id_token that fails signature, issuer,
  audience, expiry, or nonce verification
- **THEN** the login is rejected with HTTP 401 and no session is created

### Requirement: Group-based authorization from the Logto groups claim

The gateway SHALL derive the user's groups from the Logto `roles` claim mapped as groups and
map them to registry scopes via the existing group→scope mappings, including
administrative access. Users without a recognized group SHALL receive no privileged
scopes.

#### Scenario: Admin-group user receives admin scopes

- **WHEN** a user whose Logto `roles` claim contains the mapped admin role logs in
- **THEN** the user's session carries administrative scopes for the registry UI and API

#### Scenario: User without groups gets least privilege

- **WHEN** a user logs in and the `roles` claim is absent or matches no mapping
- **THEN** the user is authenticated but is granted no privileged scopes

### Requirement: Machine-to-machine API access via Logto

The gateway SHALL accept, as Bearer credentials on its REST API, access tokens issued by
the Logto machine-to-machine application via the client_credentials grant, validated
against the Logto JWKS; tokens that fail validation SHALL be rejected with HTTP 401.

#### Scenario: Automation mints and uses an M2M token

- **WHEN** an automation client requests a token from the Logto token endpoint using the
  M2M application's client credentials and calls `/api/*` with it as a Bearer token
- **THEN** the gateway validates the token against Logto's JWKS and serves the request
  according to the M2M client's configured access

#### Scenario: Invalid M2M token is rejected

- **WHEN** a Bearer token on `/api/*` is expired, signed by an unknown key, or has a
  wrong issuer
- **THEN** the gateway responds with HTTP 401 and no registry data is returned

### Requirement: Gateway-issued API tokens survive the identity swap

API tokens issued by the gateway itself SHALL remain valid across the change of identity
provider, because they are signed by the gateway's own key material and do not depend on
the IdP.

#### Scenario: API token minted before cutover keeps working

- **WHEN** a gateway-issued API token created before the identity-provider swap is
  presented after the swap
- **THEN** it authenticates exactly as before

### Requirement: Logto public endpoint on token118.com with legacy domain kept alive

`https://auth.token118.com` SHALL serve the standard OIDC endpoints (discovery,
authorization, token, userinfo, JWKS, end-session) over HTTPS with a valid certificate.
`https://logto.tokenvault.vip` SHALL remain functional for existing consumers (law-bench,
NewAPI) until they are repointed.

#### Scenario: OIDC discovery on the new domain

- **WHEN** any client fetches `https://auth.token118.com/oidc/.well-known/openid-configuration`
- **THEN** a valid discovery document is returned whose endpoints are on the
  `auth.token118.com` origin

#### Scenario: Legacy domain still works during transition

- **WHEN** an existing consumer (law-bench or NewAPI) performs its OIDC flow against
  `logto.tokenvault.vip` during the transition period
- **THEN** the flow completes successfully

### Requirement: No runtime dependency on Keycloak after cutover

After cutover is verified, the gateway SHALL operate with the Keycloak services stopped,
and stopping them SHALL NOT change any user-visible authentication behavior.

#### Scenario: Keycloak containers stopped

- **WHEN** the Keycloak and Keycloak-database containers are stopped after cutover
- **THEN** interactive login, logout, API-token use, and M2M access continue to work
