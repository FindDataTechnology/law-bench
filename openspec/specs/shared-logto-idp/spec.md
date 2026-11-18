# shared-logto-idp Specification

## Purpose

Observable behavior contract for the shared Logto identity provider at
auth.token118.com, which law-bench, NewAPI, and the AI Gateway & Registry depend on for
interactive sign-in and machine-to-machine tokens.

## Requirements

### Requirement: Password sign-in succeeds for valid credentials

For any application on any tenant served by the instance, submitting a correct
username/email + password SHALL complete the password verification and return the user to
the relying application's redirect target with a valid authorization code. Invalid
credentials SHALL be rejected with a credentials error; every verification attempt SHALL
produce an audit log entry.

#### Scenario: Gateway admin signs in

- **WHEN** the `admin` user submits correct credentials on the gateway sign-in page
- **THEN** the password verification succeeds and the browser is redirected back to
  `https://mcp.token118.com` with an authenticated session

#### Scenario: Invalid password is counted and rejected

- **WHEN** a user submits a wrong password
- **THEN** the attempt is rejected with a credentials error AND a sentinel/audit record
  of the failed attempt is persisted

### Requirement: Token grants are stable

The OIDC token endpoint SHALL reliably complete client_credentials grants (M2M) without
hanging or returning empty responses, across container restarts and sustained use.

#### Scenario: M2M grant works after restart

- **WHEN** an M2M client requests a token immediately after a Logto container restart
- **THEN** the token endpoint responds within normal latency with a valid access token

### Requirement: Database schema tracked against the running release

The Logto database SHALL carry the alteration bookkeeping for the running release (the
alterations table exists and matches the deployed schema), such that the official CLI
reports the database as up-to-date for the pinned image version.

#### Scenario: Alteration status is clean

- **WHEN** the Logto CLI's alteration check runs against the database for the pinned
  image version
- **THEN** it reports the schema as up to date (or the repair deploys the missing
  alterations successfully)

### Requirement: Image version pinned

The `idp-logto` container SHALL run a digest/version-pinned image recorded in the compose
file and deploy notes — not a mutable `latest` tag — so runtime behavior is reproducible.

#### Scenario: Compose references a pinned image

- **WHEN** the `idp-logto` service definition is inspected
- **THEN** the image reference resolves to an immutable version/digest, not `latest`

### Requirement: Management API path functional

The Logto Management API SHALL be reachable with valid M2M credentials: at minimum, the
built-in management M2M application (`m-default`) SHALL have a working secret, or the
broken credential SHALL be rotated/retired with the outcome documented.

#### Scenario: Management API authentication works

- **WHEN** a valid management M2M credential is used to call a read-only management API
  endpoint
- **THEN** the call succeeds (or, if the legacy `m-default` credential was retired, the
  replacement path is documented and works)

### Requirement: Relying applications keep working across the repair

law-bench and NewAPI OIDC flows SHALL continue to work after the repair: discovery
documents on both hostnames, login redirects, and (for the gateway) M2M grants.

#### Scenario: Post-repair consumer check

- **WHEN** after the repair the discovery endpoints, law-bench login entry, NewAPI OIDC
  entry, and gateway M2M grant are exercised
- **THEN** all respond successfully
