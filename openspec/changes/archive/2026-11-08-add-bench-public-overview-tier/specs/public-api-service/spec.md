# public-api-service Specification（delta）

## Purpose

key-only fail-closed 姿态上刻入唯一窄豁免：`bench-public-overview` 概览路由匿名可达。豁免单点、精确路径、可默认拒绝；其余全部路径的认证姿态保持原样。

## MODIFIED Requirements

### Requirement: Key-only auth posture on the public pod

The public app SHALL resolve caller identity via the `X-API-Key` channel. The session-cookie and Logto-JWKS Bearer resolution paths SHALL remain registered (so the shared `get_current_user` dependency is reused unchanged) but SHALL be effectively dormant on the public pod because no browser login is mounted and the pod is not configured to reach Logto's JWKS across the border. A valid `X-API-Key` SHALL authenticate the request; an absent key (with no other credential) SHALL yield `401`, **with exactly one exemption: the overview route(s) mounted by `bench-public-overview` (精确路径 `/api/public/overview`) MAY be registered in the app's exempt-path mechanism and reached anonymously; the exemption SHALL NOT cover sibling paths, prefixes, or wildcards, and absent/broken exemption registration SHALL fail closed to 401**. Key *issuance* (`POST /api/keys`) SHALL NOT be available on the public pod — keys are issued on the origin and handed to China callers out-of-band; the public pod only *verifies* them.

#### Scenario: Valid API key authenticates a public request

- **WHEN** a request to `GET /api/contracts/sale` carries `X-API-Key: lbk_<valid>` and no cookie/Bearer
- **THEN** the system resolves the identity from the API key and the request proceeds without `401`

#### Scenario: Missing key is rejected

- **WHEN** a request to `GET /api/contracts/sale` carries no `X-API-Key` and no cookie/Bearer
- **THEN** the system responds `401` with a JSON body `{"error": "authentication required"}`

#### Scenario: Key issuance is not reachable from the public pod

- **WHEN** `POST /api/keys` is requested against the public app (even with a valid existing key)
- **THEN** the system responds `404` (the `auth` router carrying `/api/keys` is not mounted)

#### Scenario: Overview exemption is the only anonymous path

- **WHEN** a request without any credential hits `GET /api/public/overview` versus any sibling path (e.g. `/api/public/overview/x`, `/api/contracts`)
- **THEN** the overview route returns `200` (anonymous, rate-limited per `bench-public-overview`) while every sibling path responds `401`
