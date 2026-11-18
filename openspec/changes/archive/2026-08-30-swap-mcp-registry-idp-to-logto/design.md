# Design: swap-mcp-registry-idp-to-logto

## Context

The gateway's auth-server has two layers (verified by reading `/opt/mcp-gateway-registry/auth_server`):

1. **Login flow — YAML-driven and generic.** `oauth2_providers.yml` declares per-provider
   endpoints, client credentials, and claims mapping (`auth_url`, `token_url`,
   `user_info_url`, `logout_url`, `username/groups/email/name_claim`, `enabled`).
   `/api/auth/auth/{provider}` and `/oauth2/callback/{provider}` run the code+PKCE flow
   generically off this file.
2. **Token verification — factory classes, fail-closed.** `providers/factory.py`
   dispatches to six hardcoded classes (keycloak, cognito, entra, okta, auth0,
   pingfederate); anything else raises `Unknown auth provider`. The callback verifies the
   id_token via the class (`validate_id_token`: JWKS + issuer + audience + nonce) and
   denies the login on any failure — an unclassable OIDC provider cannot log in.

Downstream of login, everything is IdP-agnostic: sessions live in Mongo, API access
tokens are minted by the auth-server itself (`HS256` with the shared `SECRET_KEY`),
and authorization is group→scope mappings in Mongo keyed off the session's groups.

The box already runs shared Logto (`idp-logto`, network `tokenvault-idp_default`,
public endpoint `https://logto.tokenvault.vip`, standard OIDC discovery, claims include
`username`, `email`, `roles`, `organizations`) serving law-bench and NewAPI. The gateway
stack runs on `mcp-gateway-registry_default` — the two networks are currently
unconnected.

## Goals / Non-Goals

**Goals**: one login system (Logto) for the gateway; retire Keycloak + its Postgres;
public Logto endpoint on `auth.token118.com` with the legacy domain kept working;
automation (M2M) keeps an equivalent client_credentials path.

**Non-Goals**: repointing law-bench and NewAPI to the new Logto domain (follow-up
change); migrating Keycloak users or audit history (registry is empty); upstreaming the
provider patch (optional follow-up); touching registry catalog data.

## Decisions

### D1 — Real provider class, not brokering, not an auth0 alias

Add `providers/logto.py` + a `logto:` entry in `oauth2_providers.yml` + a factory
branch. The class mirrors `keycloak.py`'s shape: a JWKS URL, a valid-issuer list built
from the configured external URL, `validate_token` (M2M) and `validate_id_token`
(login), plus optional M2M client config.

- *Alternative: Keycloak identity brokering* — zero code, but Keycloak stays as token
  minter; defeats the purpose.
- *Alternative: point the auth0 adapter at Logto* — endpoint dialects differ
  (`/oauth/token` vs `/oidc/token`, `/userinfo` vs `/oidc/me`); rejected after checking
  both sides.
- *Alternative: yml-only entry* — login redirects would work, but the fail-closed
  id_token chokepoint calls the factory and would 401 every login. Rejected.

The patch is three files in a stack we self-build (`build_and_run.sh` → own ECR
namespace), kept as a local commit pinned against the upstream commit currently
deployed (`d40a5a0f…`).

### D2 — Internal/external URL split over a joined Docker network

`auth-server` attaches the external network `tokenvault-idp_default` (declared in
compose, not ad-hoc `docker network connect`, so it survives re-creates). Server-to-server
calls (token, userinfo, JWKS) use `LOGTO_URL=http://idp-logto:3001`; browser-facing
`auth_url`/`logout_url` use `LOGTO_EXTERNAL_URL=https://auth.token118.com`. The
valid-issuer list contains only the external URL.

- *Alternative: hairpin through the public URL* — zero plumbing but puts Caddy + TLS on
  the token-exchange hot path; rejected. This split mirrors the existing
  `KEYCLOAK_URL`/`KEYCLOAK_EXTERNAL_URL` pattern, so the class inherits proven
  issuer-handling shape.

### D3 — M2M via Logto machine-to-machine application

Create a Logto M2M application; the automation script swaps the Keycloak token endpoint
for Logto's `/oidc/token` with the new client credentials. The provider class validates
those JWTs via `validate_token` (signature + issuer + expiry; audience lenient, matching
the cognito class's `verify_aud: False` precedent for M2M tokens). If Logto requires an
API resource indicator for M2M tokens, register `https://mcp.token118.com/api` and have
the script request it.

- *Alternative: static `REGISTRY_API_TOKEN` mode* — full-admin single key, no rotation;
  security downgrade; stays disabled.
- *Alternative: admin-minted HS256 tokens only* — capped at 24 h TTL and minting needs an
  interactive session; poor for automation. Kept as documented emergency fallback.

### D4 — Domain migration inside this change, legacy domain kept alive

Add DNS A record `auth.token118.com → 23.144.68.246`, a Caddy site block (Let's
Encrypt, mirroring the existing `logto.tokenvault.vip` block), then switch Logto's
configured endpoint to the new domain. Both Caddy hosts keep serving the same Logto.
Because Logto derives the issuer from its endpoint setting, tokens minted after the
switch carry the new issuer — existing consumers discover the issuer dynamically via
each host's discovery document, but **law-bench and NewAPI logins are verified
immediately after the switch**, before any gateway work, and the rollback is a single
setting revert.

### D5 — Groups via Logto custom JWT claim

Use Logto's custom JWT (or organizations/roles → claim) to emit a `groups` array; the
yml maps `groups_claim: groups`. The admin group name must match the existing Mongo
group→scope mapping that currently confers admin (established by the Keycloak setup
scripts) — aligned in a task before cutover. Absent/misconfigured claim yields
least-privilege (authenticated, no admin), which is the safe failure direction.

### D6 — Cutover order and rollback

Phase order: domain (with legacy-consumer verification) → Logto applications → patch +
build → env/compose switch → verification suite → stop Keycloak services (volumes
retained until archive). Rollback at any point: restore the `.env`/compose backups and
restart the stack with Keycloak services enabled; Logto-side artifacts (apps, endpoint
setting) are independently revertible.

## Risks / Trade-offs

- [Issuer change breaks law-bench/NewAPI OIDC validation] → verify both logins right
  after the Logto endpoint switch; single-setting revert if either fails.
- [Logto M2M tokens demand a resource/audience] → register the API resource and update
  the automation script; audience validation in the class is lenient by design.
- [Groups claim misconfigured → admin locked out of admin UI] → verify with a test user
  pre-cutover; Keycloak rollback path remains until archive.
- [Network join breaks on compose re-create] → external network declared in compose
  (persistent), not imperative `docker network connect`.
- [Patch drift vs upstream] → three-file minimal diff pinned to deployed commit
  `d40a5a0f…`; upstream PR as optional follow-up.

## Migration Plan

1. DNS + Caddy for `auth.token118.com`; switch Logto endpoint; verify discovery on new
   domain **and** logins on law-bench + NewAPI via legacy domain.
2. Create Logto traditional-web app (redirect `https://mcp.token118.com/oauth2/callback/logto`),
   M2M app, and the `groups` custom-JWT claim; note credentials.
3. Patch auth-server (provider class, factory branch, yml entry) and rebuild.
4. Update `.env` (`AUTH_PROVIDER=logto`, `LOGTO_*` vars) and compose (external network
   join; Keycloak services kept but unused during verification).
5. Restart auth-server; run the verification suite: interactive login + logout, admin
   scopes for the mapped group, M2M mint + `/api/*` call, pre-cutover API token still
   valid, `/health` and `/api/version` green.
6. Stop Keycloak + keycloak-db; retain volumes; update the admin-automation runbook.

## Open Questions

- Exact admin group name in the current Mongo `group_mappings` (align at implementation;
  does not change the approach).
- Whether/when to upstream the provider patch (follow-up decision).
