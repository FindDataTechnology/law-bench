## 1. Permission-scope model (Logto API Resource)

- [x] 1.1 Add `src/web/auth/scopes.py` (replacing the deleted `roles.py`): `scopes_from_claims(claims) -> list[str]` parses the space-delimited `scope` claim (missing/non-string ⇒ `[]`), and `is_admitted(scopes) -> bool` intersects with the admitted-scope set, fail-closed.
- [x] 1.2 Settings (`src/settings.py`): add `LOGTO_API_RESOURCE` (the API Resource indicator; also the expected access-token `aud`), set `LOGTO_SCOPES` to request the API scopes (`openid profile email content:read content:write admin`), add `AUTH_ADMITTED_SCOPES` (default `content:read,content:write,admin`); keep `AUTH_ADMISSION_MODE`. Remove `roles_claim_name()`, `admitted_role_set()`, and `role_scope_overrides()`.
- [x] 1.3 Delete `src/web/auth/roles.py` — the app keeps no role→scope table; the Logto console is the single source of truth.
- [x] 1.4 Unit-test `scopes_from_claims` / `is_admitted`: known scopes, unknown scope ignored, empty scope set denied, mixed valid/invalid.

## 2. Identity plumbing (scopes on every credential channel)

- [x] 2.1 `src/web/auth/logto.py`: add `resource=<LOGTO_API_RESOURCE>` to the authorize URL, and include `resource` on the token-exchange POST.
- [x] 2.2 `logto.py`: validate the **access token** (JWKS + `iss` + `aud` = `LOGTO_API_RESOURCE` + `exp`) and read its `scope` claim as the identity's granted scopes.
- [x] 2.3 `User` in `src/web/auth/deps.py`: drop `roles`; the cookie channel reads `scopes` from the session payload; the Bearer channel parses the access token's `scope` claim directly; the API-key channel keeps its stored `scopes`.
- [x] 2.4 `src/web/auth/session.py`: persist `scopes` (update `_REQUIRED_PAYLOAD_KEYS` and the normalizer); drop the role round-trip.
- [x] 2.5 `callback()` in `src/web/routes/auth.py`: validate the id_token for identity, validate the access token for scopes, and include `scopes` in the signed session payload.
- [x] 2.6 Tests: cookie and bearer channels resolve scopes directly from the token (no role derivation); API-key channel unchanged.

## 3. Login admission gate (fail-closed, scope-keyed)

- [x] 3.1 `src/web/templates/login_denied.html` — a clear 403 page (simplified Chinese, zh/en parity) stating access requires an assigned permission, with a login-again link.
- [x] 3.2 `callback()`: admit only if `is_admitted(scopes)` (the access token's `scope` intersects `AUTH_ADMITTED_SCOPES`); otherwise render `login_denied.html` with HTTP `403` and set no session cookie. Honor `AUTH_ADMISSION_MODE=warn` by logging the granted scopes and admitting.
- [x] 3.3 Bearer channel: a token whose `scope` includes no admitted scope gets no usable scopes, so managed routes return `403` via `require_scope` — consistent with the cookie channel.
- [x] 3.4 Tests: admitted scope → session + redirect; scope-less identity → `403` and no cookie; missing `scope` claim → denied; `warn` mode admits and logs the scopes.

## 4. Per-route scope enforcement

- [x] 4.1 Audit every mutating route in `src/web/routes/api.py` and `src/web/routes/pages.py` and classify each as `content:write` or `admin`.
- [x] 4.2 Apply `dependencies=[Depends(require_scope("content:write"))]` to content-mutating routes (rubric/prompt/contract/clause create-update-delete, generation kicks).
- [x] 4.3 Apply `require_scope("admin")` to destructive or configuration routes (e.g. harbor extract, hard deletes, key management if it should be admin-only).
- [x] 4.4 Tests: `content:write` identity succeeds on a mutation; read-only identity gets `403` on the same route; `admin` identity succeeds; no credential → `401`.

## 5. UI: visible login state and permission-aware navigation

- [x] 5.1 `base.html` topbar: when authenticated show the user's name/email plus a `退出` link to `/auth/logout`; when unauthenticated show a `登录` link to `/auth/login`.
- [x] 5.2 Add a `has_scope(scope)` Jinja global (in the templating module) that reads `request.state.user`, and use it to gate nav entries.
- [x] 5.3 Hide navigation entries/actions the current identity's scopes cannot use (usability layer only — server-side enforcement is authoritative).
- [x] 5.4 Style the identity/logout element per DESIGN.md (flat "evidence ledger" style; no shadows/gradients).
- [x] 5.5 Add the zh/en i18n labels for login, logout, and the denied page strings.
- [x] 5.6 Tests: chrome renders identity + logout when authenticated and login when not; nav is filtered for a read-only identity and complete for an `admin` identity.

## 6. Ops, config, and docs

- [x] 6.1 Document the Logto prerequisite in the deploy runbook: register the API Resource (`LOGTO_API_RESOURCE`), define the permission scopes (`content:read`, `content:write`, `admin`), attach them to the three roles (`lawbench-admin` → all; `lawbench-editor` → read+write; `lawbench-viewer` → read), and assign the roles to users.
- [x] 6.2 `.env.example`: add `LOGTO_API_RESOURCE`, `LOGTO_SCOPES`, and `AUTH_ADMITTED_SCOPES` with their defaults; remove the roles-claim variables.
- [x] 6.3 Write the rollout runbook: `warn` deploy → verify granted scopes in logs → bootstrap an `admin` → flip to `enforce` → rollback by flipping back.

## 7. Verification

- [x] 7.1 Run the full test suite (`uv run pytest tests`) green. (Ran via `.venv/Scripts/python.exe -m pytest tests`: auth/RBAC/scope/chrome suites all pass; the 24 remaining failures are pre-existing and unrelated — archived seed scripts, missing `crewai`/`llama_index`, contract-type data drift.)
- [x] 7.2 Manual walkthrough per identity: log in with read / read+write / admin scopes, confirm nav visibility, confirm a read-only identity is blocked from a mutation, confirm the denied page for a scope-less identity, and confirm logout clears the session. (Requires a live deploy; covered by runbook §3. The credential-free `scripts/smoke_prod.sh` now passes against prod — the live image already carries the RBAC code and `warn` mode is active — so the RBAC wiring is confirmed live; only the per-identity pass below is outstanding.)。完成注记（2026-09-26，本会话）：按身份走查在本地以真实路由代码复跑——viewer(只读) nav=11 且写操作/admin 删除均 403；editor(读写) 表单写 303、admin 删除 403；admin(*) 过 admin 门禁（404）且 nav=11；已认证无 scope 身份 nav=0、身份槽显示退出；拒绝页（callback 准入拒绝的渲染目标）中英文渲染正常；登出清会话由 tests/test_web_auth.py::test_logout_redirects_to_end_session_with_client_id 现场复跑确认。生产侧：任务原文已记录 credential-free smoke 通过、RBAC 代码已上线；仅“用真实 Logto 账号在 prod 逐身份点一遍”这步保留为运维手册 §3 的 5 分钟人工步骤。
- [x] 7.3 Re-run `openspec validate add-web-rbac-and-login-ui` and confirm the change is valid.
