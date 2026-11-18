## Context

See `proposal.md` — Why. Current state that shapes the approach:

- Auth is already a hybrid resolver in `src/web/auth/deps.py`: cookie → Bearer JWT →
  API key, all converging on `User` and attached to `request.state.user`. The
  constructor-level `Depends(get_current_user)` in `src/web/app.py` gates every route;
  `require_scope()` (deps.py) already implements scope checks (with a `"*"` wildcard)
  but is **never wired to a route**.
- The session cookie payload is built in `src/web/routes/auth.py` `callback()` and signed by
  `src/web/auth/session.py`.
- `base.html` already receives `request` in its Jinja context (it reads `request.url.path`
  and `request.query_params`) and a `has_scope(...)` Jinja global already gates nav; template
  identity display uses `user.name`/`user.email`/`user.sub` only — templates never read roles.
- Mutating routes exist in both `src/web/routes/api.py` (JSON API) and
  `src/web/routes/pages.py` (form posts) — e.g. rubric/prompt create/update/delete — and
  must be covered uniformly.
- Identity is fully delegated to Logto; there is no local users table. `api_keys` rows carry
  their own `scopes` (deps.py API-key channel).
- Deploy target: k3s, image `sha-2c502d7` in-cluster; config via env / secrets. There is a
  temporary `samples.py` ConfigMap overlay live — unrelated but must be removed before a
  full-image redeploy.

## Goals / Non-Goals

**Goals:**
- An authorization model grounded in Logto's own RBAC: a Logto **API Resource** carrying
  permission scopes (`content:read`, `content:write`, `admin`), bundled into the
  `lawbench-admin` / `lawbench-editor` (业务编辑) / `lawbench-viewer` (只读) roles **inside
  Logto**, enforced server-side on managed routes.
- The app authorizes **only** on the access token's `scope` claim — no app-side role table,
  no second source of truth.
- A fail-closed login admission gate so only identities holding an admitted permission get a
  session.
- Visible login state (identity + logout) and permission-filtered navigation in the UI.
- A rollout that cannot lock every user out.

**Non-Goals:**
- No local user/password store; no second identity system.
- No per-clause or per-record ownership model — authorization is permission/scope level only.
- No change to the API-key transport or to the shared Logto IdP's runtime contract; the
  Logto tenant configuration (API Resource, permissions, role bundles) is an operational
  prerequisite, not code.
- No changes to `public_app.py`'s API-key-only posture.

## Decisions

### D1. Permissions arrive as OAuth scopes on the access token for a Logto API Resource

Authorization follows Logto's documented RBAC model ("permissions and scopes are the same
concept"): the tenant registers an **API Resource** with an indicator/audience
(`LOGTO_API_RESOURCE`, e.g. `https://lawbench-api.finddatatech.cloud`) and defines
permission scopes on it. Roles bundle permissions; users get roles. Because roles are only
permission bundles, the app never needs to know a role name.

`GET /auth/login` sends `resource=<indicator>` and requests the permission scopes; the
token exchange includes `resource=<indicator>` again. The resulting **access token** carries
a space-delimited `scope` claim = the intersection of requested scopes and the user's
granted permissions. The app parses that claim (`payload["scope"].split(" ")`) as the
identity's authoritative scopes.

Cookie-flow nuance: the **ID token** is an identity token and does **not** carry API-resource
scopes. We validate the ID token only for identity (`sub`/`name`/`email`) and validate the
**access token** (JWKS + `aud`=`LOGTO_API_RESOURCE` + `exp`) to obtain `scope`. The Bearer
channel already carries an access token, so the same parse applies.

*Alternatives:* (a) request a custom `roles` claim and map role→scope in an app-side table —
rejected: it is a second source of truth (changing a role's powers needs a code redeploy,
not a console change) and deviates from Logto's model; (b) call the Logto Management API per
login to resolve role→permission — rejected: extra network dependency and credentials on the
request path.

### D2. Authorize on the token's `scope` claim; keep `require_scope()`, drop the app-side table

`User.scopes` is set directly from the parsed `scope` claim on the cookie and Bearer
channels (the API-key channel keeps its stored `scopes`). Managed routes get
`dependencies=[Depends(require_scope("content:write"))]` (mutations) or
`require_scope("admin")` (destructive/config); the wildcard `"*"` (granted by the Logto
`admin` permission, which we map to `*`) matches every check. `src/web/auth/roles.py` and
its `ROLE_SCOPES` table are **deleted**; a small `src/web/auth/scopes.py` replaces it with
`scopes_from_claims(claims)` (parse the `scope` claim) and `is_admitted(scopes)`.

The internal scope namespace (`content:read`, `content:write`, `admin`) is now the Logto
permission namespace — the same strings are defined in the Logto console and checked by
`require_scope`, so the console is the single source of truth.

*Alternatives:* (a) a new `require_role(...)` dependency — rejected: two parallel
authorization primitives; scopes are already modeled on `api_keys` and checked by
`require_scope`; (b) hard-coding role checks inside handlers — rejected: easy to forget on
new routes; (c) keep the app-side `ROLE_SCOPES` table as a fallback — rejected: it re-creates
the drift D1 removes.

### D3. Admission gate at `/auth/callback`, keyed on granted scopes, fail-closed

After the access token validates, parse its scope set; if the intersection with the
admitted-scope set (default `{content:read, content:write, admin}`, env-overridable) is
empty, render a new `login_denied.html` with HTTP `403` and set no cookie. A valid token
with no admitted scope yields no session. The Bearer channel is inherently scope-based, so a
token with no admitted scope simply fails `require_scope` at the route (`403`). The API-key
channel is exempt from the gate: keys are admin-provisioned with explicit scopes.

*Alternatives:* (a) admit login then hide/deny per route — rejected by the user's choice
("登录即拒"); (b) gate only the cookie channel — rejected: leaves Bearer tokens as a
privilege-escalation path.

### D4. Staged rollout via `AUTH_ADMISSION_MODE` (`warn` then `enforce`)

`warn` logs each identity's granted scopes and admits everyone (so the Logto API Resource /
permission wiring can be verified without lockout); `enforce` (default in code, but the
deploy flips it last) applies D3. This makes the cutover observably safe.

*Alternatives:* no flag, hard cutover — rejected: one mis-ordered config step locks all users
out with no in-band way to see why.

### D5. UI visibility via `request.state.user` + a Jinja `has_scope` helper

`base.html` renders the identity and a `/auth/logout` link when authenticated, and a
`/auth/login` link otherwise; nav entries wrap in a `has_scope(...)` Jinja global. No page
route needs editing to expose the user. Navigation filtering is usability only — the
server-side `require_scope` checks are authoritative.

*Alternatives:* thread `user` into every `TemplateResponse` context — rejected: dozens of
call sites, easy to miss one, and `request` is already in context.

## Risks / Trade-offs

- **Lockout if the API Resource / permissions / scopes are mis-wired** → D4 `warn` mode + a
  documented cutover order; `enforce` is flipped only after logs confirm scopes for real
  users.
- **A token minted for the wrong resource carries no `aud` we accept** → `LOGTO_API_RESOURCE`
  is required for the gate to be meaningful; validate `aud` and log the parsed scopes in
  `warn` mode before enforcing.
- **Existing sessions carry no scopes** → old cookies resolve to no scopes and are denied
  after the cutover; acceptable (users re-login). Called out in the migration plan.
- **Nav filtering mistaken for security** → spec states server-side enforcement is
  authoritative; tests assert a route-level `403` for a read-only identity, not just hidden
  nav.
- **Scope-coverage gaps on less-obvious mutating routes** → the task list includes an
  explicit audit of `api.py` + `pages.py` mutation routes so none is left ungated.
- **Tenant prerequisite is out-of-band** → treated as a deploy prerequisite with a
  verification step (observe `scope` in `warn` logs) before enforcement.

## Migration Plan

1. **Logto tenant**: register the API Resource (`LOGTO_API_RESOURCE`), define the permission
   scopes (`content:read`, `content:write`, `admin`), attach them to the three roles
   (`lawbench-admin` → all; `lawbench-editor` → read+write; `lawbench-viewer` → read), and
   assign the roles to users.
2. **Deploy in `warn`**: ship the code with `AUTH_ADMISSION_MODE=warn`; exercise a login per
   role and confirm the granted scopes in logs.
3. **Bootstrap admin**: ensure at least one user holds a role granting `admin` (or all three
   scopes) before enforcement.
4. **Enforce**: set `AUTH_ADMISSION_MODE=enforce`, redeploy, verify admitted login succeeds
   and a scope-less user gets the `403` page.

**Rollback**: set `AUTH_ADMISSION_MODE=warn` (or revert to the prior image) and redeploy —
no schema or data migration is involved, so rollback is a config flip.

## Open Questions

- None blocking. The exact split of which routes are `admin`-only vs `content:write` is
  resolved during the route audit (`tasks.md` §4) without changing the approach or specs.
