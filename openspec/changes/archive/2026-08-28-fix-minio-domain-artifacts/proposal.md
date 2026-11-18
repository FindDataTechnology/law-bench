# fix-minio-domain-artifacts

## Why

After the 2026-08-27 domain migration added `file.token118.com` → US MinIO `:30900` (commit 61afc15), files stopped being visible/downloadable on the web contract page. Investigation found that `src/settings.py`'s `minio_host` parsing silently produces an **empty** `MINIO_ENDPOINT` when the secret value lacks a URL scheme (`file.token118.com` instead of `https://file.token118.com`), so every artifact download/upload raises `RuntimeError("minio_host is not set")` per request — no fail-fast at boot, and the Postgres-backed `/samples` listing keeps working, hiding the breakage. The on-box wiring (secret value, US Caddy site block, TLS) also needs verification because it lives outside git.

## What Changes

- Diagnose on-box (Phase 0): read the actual `minio_host` secret value, probe `https://file.token118.com/minio/health/live` from the origin pod, reproduce the failing download, and read the pod logs to classify the failure (empty-endpoint RuntimeError vs connection error vs redirect/signature error).
- Fix the identified root cause (exactly one, per diagnosis): correct the secret to a full URL with scheme; or add the missing US Caddy site block / ACME cert for `file.token118.com`; or switch the secret from `http://` to `https://` to avoid a redirect the minio SDK cannot follow.
- Fail fast in code: `src/settings.py` SHALL validate that `minio_host` and `MINIO_PUBLIC_HOST` (when set) are full URLs with an `http://` or `https://` scheme, raising `ConfigError` at import/startup with a message naming the offending variable and value instead of silently yielding an empty endpoint.
- Deployment guidance (documented, decided in design): the origin pod's own data path keeps an in-cluster/NodePort MinIO endpoint (`http://23.144.68.246:30900`) and `file.token118.com` is reserved for external consumers and the China mirror sync — removing the app's runtime dependency on Caddy/ACME. Optionally pin a `hostAliases` entry for `file.token118.com` where the domain is used in-cluster.
- Verification: `/samples` lists rows, artifact downloads return 200 docx/pdf, a fresh `generate-stored` round-trip works on the origin, and the China public pod (separate `MINIO_PUBLIC_HOST` path) is unaffected.

Non-goals: changing the download endpoint contract, the samples listing UI, or the China mirror sync cadence.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `contract-artifact-storage`: adds a fail-fast configuration requirement — MinIO endpoint env vars (`minio_host`, `MINIO_PUBLIC_HOST`) must be full URLs with scheme; a scheme-less value is rejected at startup with `ConfigError` instead of failing per-request at download/upload time.

## Impact

- `src/settings.py` — scheme validation for `minio_host` / `MINIO_PUBLIC_HOST` (import-time `ConfigError`), plus comment updates.
- `src/contracts/artifacts.py` — `_client()`'s `RuntimeError` path becomes unreachable for scheme-less values (kept as a defensive guard).
- `tests/` — new unit tests for the settings validation (valid/missing/scheme-less, public-host override present/absent).
- Deployment (operational, not in-repo): k8s secret `minio_host` value, US-box Caddy site block for `file.token118.com`; `deploy/deployment.yaml` optionally gains a `file.token118.com` hostAliases pin (code change in repo).
- Runtime behavior change: a misconfigured endpoint now crashes the app at startup (fail-closed) rather than serving 500s on artifact routes — intentional and consistent with the existing fail-closed auth config posture.
