# Tasks: swap-mcp-registry-idp-to-logto

## 1. Domain migration (auth.token118.com)

- [x] 1.1 Add DNS A record `auth.token118.com → 23.144.68.246` and a Caddy site block
  (Let's Encrypt) mirroring the existing `logto.tokenvault.vip` block; verify
  `https://auth.token118.com/oidc/.well-known/openid-configuration` returns a valid
  discovery document
- [x] 1.2 Switch the Logto endpoint config to `https://auth.token118.com` (admin
  console → Settings → Endpoints), then verify: discovery on the new domain, **and**
  interactive logins still work on law-bench (`lawbench.token118.com`) and NewAPI
  (`www.token118.com`) via the legacy domain — if either breaks, revert the setting and
  stop
- [x] 1.3 Confirm the legacy Caddy host `logto.tokenvault.vip` remains live (both hosts
  front the same Logto)

## 2. Logto applications and claims

- [x] 2.1 Create a Logto traditional-web application for the gateway (redirect URI
  `https://mcp.token118.com/oauth2/callback/logto`, post-logout redirect
  `https://mcp.token118.com/`); record client id/secret out-of-band
- [x] 2.2 Create a Logto machine-to-machine application; record client id/secret; if
  M2M tokens require an API resource, register `https://mcp.token118.com/api` and
  attach it
- [x] 2.3 Groups mechanism: created Logto role `registry-admins` (type User) and assigned it to the admin user; the gateway maps the Logto `roles` claim (userinfo) as groups via yml (custom JWT not needed)
  roles), assign the admin group to the test user, and decode a sample id_token to
  confirm the claim is present
- [x] 2.4 Check the registry Mongo `group_mappings` for the group name that currently
  confers admin; align the Logto group name (or the mapping) so the admin scope chain
  closes

## 3. Auth-server patch and build (on-box, /opt/mcp-gateway-registry)

- [x] 3.1 Record the deployed upstream commit (`d40a5a0f…`) and branch the local checkout
  for the patch
- [x] 3.2 Add `auth_server/providers/logto.py` mirroring `keycloak.py`: internal base
  URL for token/userinfo/JWKS, external-URL valid-issuer list, `validate_token`
  (signature + issuer + expiry, lenient audience) and `validate_id_token` (strict,
  nonce-aware)
- [x] 3.3 Add the `logto:` entry to `auth_server/oauth2_providers.yml`
  (auth_url/logout_url on the external URL; token_url/user_info_url on the internal
  `http://idp-logto:3001` URLs; claims mapping `username`/`groups`/`email`/`name`) and
  the `logto` branch in `providers/factory.py`
- [x] 3.4 Add `LOGTO_*` env plumbing (external URL, internal URL, client id/secret, M2M
  client id/secret, enabled flag) to the `.env` template with the same comment style as
  the other providers
- [x] 3.5 Rebuilt via `docker build -f docker/Dockerfile.auth -t mcp-auth-server:logto .` (3 iterations: provider, ES384, scopes); image-internal import + yml checks passed
  tests for the provider pass on the box

## 4. Compose and network wiring

- [x] 4.1 Back up `/opt/mcp-gateway-registry/.env` and `docker-compose.yml` (rollback
  artifacts)
- [x] 4.2 Declare the external network `tokenvault-idp_default` and attach it to the
  `auth-server` service; verify `auth-server` resolves `idp-logto` and reaches
  `http://idp-logto:3001/oidc/jwks`
- [x] 4.3 Set `AUTH_PROVIDER=logto` with the `LOGTO_*` values (Keycloak vars left in
  place, unused, for rollback); restart the auth-server container

## 5. Cutover verification

- [x] 5.1 Interactive: browser login verified end-to-end — gateway login page → Logto
  sign-in → consent → callback → console session as **mcpadmin**. Unblocked by
  `repair-shared-logto-instance` (china k3s DNS pollution pin + production Logto is the
  china-box k3s pod; gateway `LOGTO_URL` repointed to `https://auth.token118.com`;
  first-party scopes `profile email roles`)
- [x] 5.2 Authorization: mcpadmin (registry-admins role) shows "🔑 Admin Access" in the
  console; users without the role get no privileged scopes (group→scope mapping intact)
- [x] 5.3 M2M: mint a client_credentials token from Logto and call `GET /api/servers`
  with it (expect 200); invalid/expired token → 401
- [x] 5.4 API tokens: a gateway-issued API token created before cutover still
  authenticates on `/api/*`
- [x] 5.5 Health: `/health` and `/api/version` green through the public URL; update the
  admin-automation script (token endpoint + credentials) and re-run the inventory call

## 6. Retirement and cleanup

- [x] 6.1 Stop the `keycloak` and `keycloak-db` containers and disable their compose
  services; confirm login, logout, API tokens, and M2M all still work (spec: no runtime
  dependency on Keycloak)
- [x] 6.2 Remove Keycloak bootstrap secrets (`INITIAL_ADMIN_PASSWORD`,
  `KEYCLOAK_M2M_CLIENT_SECRET`, etc.) from the active `.env`; retain Keycloak volumes
  until the change is archived
- [x] 6.3 Document the new auth posture (Logto endpoints, app names, M2M flow) in the
  deploy notes in this repo; note the follow-ups: repoint law-bench/NewAPI to
  `auth.token118.com`, optional upstream PR for the provider
