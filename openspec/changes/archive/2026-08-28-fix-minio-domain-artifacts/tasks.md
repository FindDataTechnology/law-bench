# fix-minio-domain-artifacts — Tasks

## 1. Code hardening (no on-box access needed)

- [x] 1.1 Add `_validated_minio_url(name, value)` helper in `src/settings.py`: reject non-empty values without an `http`/`https` scheme or with an empty netloc, raising `ConfigError` naming the env var and value (design D1); derive `MINIO_ENDPOINT`/`MINIO_SECURE` and `MINIO_PUBLIC_ENDPOINT`/`MINIO_PUBLIC_SECURE` from the validated values; keep the `http://localhost:9000` default for unset/empty `minio_host`
- [x] 1.2 Update the `_client()` comment in `src/contracts/artifacts.py` to point at the settings validation; keep the `RuntimeError` as a defensive guard (design D2)
- [x] 1.3 Add tests covering: scheme-less `minio_host` raises `ConfigError` naming the var; scheme-less `MINIO_PUBLIC_HOST` raises; full URLs produce expected `MINIO_ENDPOINT/SECURE` and `MINIO_PUBLIC_ENDPOINT/SECURE`; unset override falls back to origin values (design D5)
- [x] 1.4 Grep tests for direct `MINIO_ENDPOINT`/`minio_host` env manipulation and fix any that now trip the validation; run the affected test files locally

## 2. On-box diagnosis (needs ssh-mcp tools or operator-pasted output)

- [x] 2.1 Read the origin pod's MinIO secret value: `kubectl -n law-bench get secret <secret> -o jsonpath='{.data.minio_host}' | base64 -d` — record scheme, host, port
  - Verdict: `http://minio.minio.svc.cluster.local:9000` — valid full URL, in-cluster service. Branch A ruled out.
- [x] 2.2 Probe the domain from inside the origin pod: `curl -sI https://file.token118.com/minio/health/live` (expect 200; also try `http://` to detect a redirect)
  - Verdict: HTTPS 200 via Caddy; `http://` → 308 redirect to https (harmless — no consumer uses http). Reachable from China too. Branch B and C ruled out for the app.
- [x] 2.3 Reproduce the page symptom: `curl -o /dev/null -w '%{http_code}' 'https://lawbench.token118.com/api/contracts/artifacts/<id>/download?format=docx'` while tailing pod logs
  - Verdict: 401 (auth middleware, expected without login); 72h of app logs show zero errors and zero authenticated visits — the app/data path was never failing.
- [x] 2.4 Classify the failure from the pod-log signature against the design D3 table (RuntimeError vs MaxRetryError vs S3Error 301/SignatureDoesNotMatch) and record the verdict
  - Verdict: **none of A/B/C** — new branch D: `file.token118.com` routes to the MinIO **S3 API** (:30900), which serves XML `AccessDenied` in a browser — there is no web file page at that domain. The MinIO web console (the file browser) is a separate service on :9001/NodePort 30901 with no domain route. Data verified intact via `mc` (3043 objects, artifacts current through 2026-08-24).

## 3. On-box fix (exactly one branch, per 2.4)

- [ ] 3.1 Branch A (empty endpoint): set the secret's `minio_host` to the full URL with scheme, `kubectl rollout restart` the deployment, retest download
  - N/A — ruled out by 2.1 (secret already a valid in-cluster URL).
- [x] 3.2 Branch B (unreachable domain): add the US-box Caddy site block `file.token118.com` → `127.0.0.1:30900`, confirm the ACME cert issued (ports 80/443 reachable), retest `curl -sI https://file.token118.com/minio/health/live`
  - Applied as the branch-D variant: `file.token118.com` → `:30900` was already correct; added the missing **console** block `file-console.token118.com` → `127.0.0.1:30901` (Caddyfile patched, validated, reloaded; backup at `/etc/caddy/Caddyfile.bak-20260828`) and set `MINIO_SERVER_URL` / `MINIO_BROWSER_REDIRECT_URL` on the minio deployment (rolled out cleanly). Cert auto-issues once the DNS A record exists (Caddy retries ~60s; current log shows NXDOMAIN as the only blocker).
- [ ] 3.3 Branch C (redirect/signature): switch the secret from `http://` to `https://`, rollout restart, retest
  - N/A — ruled out by 2.2.

## 4. End-state decision + deployment posture

- [x] 4.1 Apply design D4: revert the origin secret to the in-cluster endpoint (`http://23.144.68.246:30900`) so the app data path has no Caddy/ACME dependency, and note `file.token118.com` as the external/mirror-sync endpoint — OR, if the domain is kept for the origin, add the `file.token118.com` hostAliases pin to `deploy/deployment.yaml` mirroring the existing auth/lawbench pins
  - Already satisfied on-box: the origin secret is `http://minio.minio.svc.cluster.local:9000` (even stronger than D4 — cluster-local, no NodePort); no hostAliases pin needed since the origin app does not use the domain.
- [x] 4.2 Document the chosen endpoint posture in `docs/public-api-deploy.md` (one short paragraph: which endpoint each consumer uses)
  - Added "Endpoint posture" table under §3: origin pod / external+sync / browser-console endpoints, the console env vars, and the new fail-fast settings validation.

## 5. Verification

- [ ] 5.1 `/samples` on the origin lists rows; a docx and a pdf download both return 200 with correct content-type
  - Partially verified: unauthenticated requests correctly 401; the MinIO read path the app uses was proven with `mc` (same endpoint, bucket listing + object stat OK). Full end-to-end needs a logged-in browser session (or a short-lived API key) — deliberately not done to avoid writing to the prod `api_keys` table.
- [ ] 5.2 A fresh `POST /api/contracts/{type}/generate-stored` round-trip uploads to MinIO and returns download URLs that work
  - Blocked on authenticated access, same as 5.1.
- [ ] 5.3 China public pod unaffected: its `MINIO_PUBLIC_HOST` path still serves the China-local mirror (spot-check one download if the pod is live)
  - N/A — no `law-bench` namespace / public pod deployed on either China box yet.
- [ ] 5.4 `openspec validate fix-minio-domain-artifacts` passes; run the full settings/artifact test files
  - Validation passes; the new settings tests pass 6/6 (minimal env). The full artifact test files could not run on this Windows box (project venv fails building litellm's rust extension) — rerun in CI/the US box env before archive.
