# fix-minio-domain-artifacts — Design

## Context

The artifact read/write path is `src/contracts/artifacts.py::_client()` building a native minio SDK client from `src/settings.py` module constants: `MINIO_ENDPOINT = urlparse(minio_host).netloc` and `MINIO_SECURE = minio_host.startswith("https")`, with `MINIO_PUBLIC_ENDPOINT/SECURE` derived the same way from the optional `MINIO_PUBLIC_HOST` override. `urlparse` returns an empty `netloc` for a scheme-less value like `file.token118.com`, so today a bad secret value only surfaces as a per-request `RuntimeError` in `_client()` — while the Postgres-backed `/samples` listing keeps working, hiding the breakage (the observed "files not visible" symptom when a download is attempted).

Verified facts that constrain the design (from exploration, 2026-08-28):

- minio-py 7.2.20 (pinned in `uv.lock`) uses **path-style** URLs for custom domains — virtual-host style only for AWS/aliyuncs endpoints. Moving the endpoint from `http://23.144.68.246:30900` to `https://file.token118.com` does not change request URL shape, so no client-side addressing change is needed.
- `artifacts.py` already sets `NO_PROXY=*` and `cert_check=False`, so proxies and self-signed TLS are already tolerated.
- The origin pod (`deploy/deployment.yaml`) pins `auth.token118.com` / `lawbench.token118.com` via hostAliases because the node's DNS history is polluted; any *new* public name used from inside the cluster may need the same treatment.
- The domain wiring (`minio_host` secret value, US-box Caddy site block for `file.token118.com`, ACME cert) lives on-box, outside git — commit 61afc15 only renamed comments/hostAliases in-repo.
- The project already has a fail-closed config precedent: `check_auth_config()` / `check_public_auth_config()` raise `ConfigError` at `create_app()` when required env vars are missing.

## Goals / Non-Goals

**Goals:**

- Make a misconfigured MinIO endpoint impossible to miss: rejected at startup with a message naming the env var and value.
- Restore artifact download/generation on the origin via a correct, verified endpoint configuration.
- Keep the origin pod's own data path independent of the public-domain TLS path (Caddy/ACME).

**Non-Goals:**

- No change to the download endpoint contract, samples UI, China mirror sync cadence, or bucket layout.
- No presigned URLs / browser-direct MinIO access — downloads stay server-streamed.
- No virtual-host-style (`MINIO_DOMAIN`) support; path-style is what the pinned SDK already does and it works through Caddy.

## Decisions

### D1: Validate scheme at settings import time, not at first use

Add a `_validated_minio_url(name, value)` helper in `src/settings.py`: for each of `minio_host` and (when non-empty) `MINIO_PUBLIC_HOST`, require `urlparse(value).scheme in {"http", "https"}` and a non-empty netloc; otherwise raise `ConfigError(f"{name} must be a full URL with http(s) scheme, got: {value!r}")`. Derive `MINIO_ENDPOINT/SECURE` and `MINIO_PUBLIC_ENDPOINT/SECURE` from the validated values.

- Why import time: both pods and several scripts (`scripts/infra/sync_minio_artifacts.py` imports the same settings pattern) get the failure at boot, matching the existing `ConfigError` fail-closed posture. A `create_app()`-time check would leave scripts and the MCP server unprotected.
- Alternative rejected: validating inside `artifacts._client()` — keeps the per-request failure mode this change exists to eliminate.
- Empty `minio_host`: today `MINIO_ENDPOINT` defaults to `http://localhost:9000`. Keep the default (tests and local dev rely on it); validation only rejects non-empty scheme-less values. An explicitly-set-but-empty `minio_host` is treated as unset (default applies).

### D2: `_client()` RuntimeError stays as a defensive guard

`RuntimeError("minio_host is not set (MinIO unreachable).")` in `artifacts.py` becomes unreachable via the settings path but remains for monkeypatched/test clients. No behavior change; the comment is updated to point at the settings validation.

### D3: Operational fix is chosen by Phase 0 diagnosis, code is domain-agnostic

The repo-side fix (D1) does not care which endpoint wins. The on-box fix is one of:

| Diagnosis (pod log signature) | Fix |
|---|---|
| `RuntimeError: minio_host is not set` | secret value lacks scheme → set full URL, rollout restart |
| `MaxRetryError` / connection refused/timeout | `file.token118.com` unreachable → add US Caddy site block → `127.0.0.1:30900`, confirm ACME issued (80/443 reachable), retest |
| `S3Error 301` / `SignatureDoesNotMatch` | `http://` secret vs https redirect → use `https://` in the secret |

### D4: Origin keeps the in-cluster endpoint; the domain serves external consumers

Recommended end-state: origin pod's `minio_host` returns to `http://23.144.68.246:30900` (NodePort, no TLS hop, no Caddy/ACME dependency); `file.token118.com` is used by the China mirror sync (`sync_minio_artifacts.py --origin-host https://file.token118.com`) and any external tooling. The origin pod's data path then cannot break because of a cert renewal or Caddy reload.

- Alternative considered: origin uses `https://file.token118.com` — keeps one canonical endpoint string everywhere but couples every artifact byte to the public TLS path and the out-and-back loop through Caddy.
- If the origin ever must use the domain from inside the cluster, add a `file.token118.com` hostAliases pin to `deploy/deployment.yaml` mirroring the existing `auth`/`lawbench` pins (DNS pollution history on that node).

### D5: Tests target the parsing/validation unit, not a live MinIO

New test module `tests/test_minio_endpoint_validation.py` (or extend the existing settings-touching test) monkeypatching env / re-importing settings: scheme-less `minio_host` raises `ConfigError` naming the var; scheme-less `MINIO_PUBLIC_HOST` raises; full URLs produce the expected `MINIO_ENDPOINT/SECURE` and `MINIO_PUBLIC_ENDPOINT/SECURE`; unset override falls back. No network, no minio server fixture.

## Risks / Trade-offs

- [Fail-closed startup now crashes pods that previously limped along with 500s] → That is the point; documented in the proposal, and the error message names the exact env var + value so the operator fix is one `kubectl` command. Consistent with `check_auth_config`.
- [Import-time raise could break tests that set weird env] → Tests currently rely on the `http://localhost:9000` default which stays valid; grep for direct `MINIO_ENDPOINT` monkeypatching during implementation and adjust.
- [Phase 0 diagnosis blocked until ssh-mcp tools are live in a session] → Tasks are ordered so code-side hardening (D1/D2/D5) proceeds independently; on-box tasks can also be executed by the operator pasting command output.
- [D4 end-state is a recommendation, the box may keep the domain] → D1 makes either choice safe; D4 only removes the TLS-path coupling if adopted.

## Migration Plan

1. Land code (D1/D2/D5) — no behavior change for correctly configured deployments.
2. Phase 0 diagnosis on-box → apply the single D3 fix.
3. Adopt D4 end-state (revert origin secret to NodePort URL) or explicitly keep the domain with a hostAliases pin.
4. Rollback: revert the settings change; the secret fix is independently reversible.
