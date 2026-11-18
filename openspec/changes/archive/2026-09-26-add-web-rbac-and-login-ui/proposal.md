## Why

The workbench authenticates everyone but authorizes no one. Every route is gated by
`Depends(get_current_user)`, so any user who can complete a Logto sign-in gets the full
clause / rubric / generation / pipeline surface — there is no notion of permission, and
`require_scope()` (defined at `src/web/auth/deps.py`) is never used. The UI makes this
worse: `base.html` renders neither the current user nor a login/logout affordance, so
operators "see no login" at all.

To safely onboard 业务人员 (business/content staff) to manage backend content, the app needs
an explicit authorization model that stays on Logto's own rails: a **Logto API Resource**
carrying **permission scopes**, bundled into **roles** inside Logto, with the app
authorizing solely on the scopes the access token carries. On top of that: a hard
admission gate so only permitted identities can log in, per-route enforcement for the
managed surfaces, and a visible login state in the UI.

## What Changes

- **Permissions sourced from Logto (no app-side role table).** The tenant registers an
  **API Resource** (audience) and defines permission scopes on it — `content:read`,
  `content:write`, `admin`. Logto roles (`lawbench-admin`, `lawbench-editor` 业务编辑,
  `lawbench-viewer` 只读) bundle these permissions; the role→permission mapping lives
  **entirely in Logto**. At login the app sends `resource=<indicator>` on the authorize
  request (and again at the token exchange); the resulting **access token's `scope` claim**
  is the union of the user's granted permissions and is the app's authoritative grant.
  The app keeps **no role→scope table of its own** — `src/web/auth/roles.py` is retired.
- **Login admission gate.** `GET /auth/callback` admits only identities whose access token
  carries at least one admitted permission scope. An authenticated user with no admitted
  scope is **not** issued a session cookie and is shown a clear 403 page (simplified
  Chinese, zh/en parity).
- **Scopes carried into the session and identity.** The signed session cookie payload
  carries the resolved `scopes`; `User` carries `scopes`; `get_current_user` reads them
  directly from the token's `scope` claim so both the cookie and Bearer channels enforce
  consistently. The API-key channel keeps using its stored `scopes` directly.
- **Per-route scope enforcement.** Apply the existing `require_scope()` factory to the
  managed surfaces: content-mutating routes require `content:write`; destructive /
  configuration routes require `admin`. Read-only routes remain open to any admitted
  identity.
- **Permission-aware UI + visible login state.** `base.html` topbar shows the current user
  (name/email) and a `退出` logout link when authenticated; nav entries the current identity
  cannot use are hidden. Templates receive the resolved `User`.
- **Fail-closed on missing/unknown scopes.** No `scope` claim, empty scopes, or scopes that
  match nothing ⇒ denied admission (never an implicit admin).
- **BREAKING**: existing users whose Logto roles grant none of the admitted permissions
  will be denied at the login gate. A bootstrap admin (and the API Resource + permissions)
  must be configured in Logto before rollout (see design.md / Impact).

## Capabilities

### New Capabilities

- `web-rbac`: Permission-scoped access control for the workbench — the Logto API Resource
  and its permission scopes, the admission gate keyed on granted scopes, per-route scope
  enforcement via `require_scope()`, permission-aware navigation, and the fail-closed
  posture. Roles exist only inside Logto as permission bundles; the app never holds a
  role table.

### Modified Capabilities

- `web-auth`: `/auth/login` now requests the API Resource (`resource=<indicator>`) and its
  permission scopes; `/auth/callback` validates the **access token** and reads its `scope`
  claim, then applies the scope-admission gate (disallowed identities get 403 and no
  session cookie). The session payload carries `scopes`, and a new requirement makes login
  state visible in the UI (identity + logout link in the topbar).

## Impact

- **Code**: `src/web/routes/auth.py` (callback: validate access token, scope gate,
  login-state plumbing), `src/web/auth/logto.py` (add `resource=` to authorize + token
  exchange; add access-token validation), a new `src/web/auth/scopes.py` (parse the `scope`
  claim, admitted-scope check) replacing the deleted `src/web/auth/roles.py`,
  `src/web/auth/deps.py` (scopes on `User`, drop role derivation),
  `src/web/auth/session.py` (persist `scopes`), `src/settings.py`
  (`LOGTO_API_RESOURCE`, `LOGTO_SCOPES`, admitted-scope configuration; drop role config),
  `src/web/templates/base.html` (+ `src/web/static/style.css`), and a login-denied error
  page.
- **APIs / behavior**: browser cookie login can now end in `403` (denied permission) instead
  of a session; `/auth/logout` becomes reachable from the UI. Bearer and API-key channels
  are unchanged in transport but now subject to scope checks on managed routes.
- **Ops / external**: the Logto tenant must (a) register the API Resource and its
  permissions, (b) attach those permissions to the three roles, and (c) assign the roles to
  users. The deployment must set the API-resource indicator and the admitted-scope
  allowlist. Rollout order matters: configure the resource + permissions + a bootstrap
  admin **before** enabling the gate, or all existing users are locked out.
- **Tests**: hermetic — monkeypatched Logto / fake JWTs, no network or LLM calls.
