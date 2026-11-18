## Context

uvicorn runs behind Caddy (systemd, TLS-terminating) on host `23.144.68.246`, proxying to k3s NodePort `30820` → pod `:8010`. Caddy sends `X-Forwarded-Proto: https` / `X-Forwarded-Host`. Without `--proxy-headers`, uvicorn does **not** install its `ProxyHeadersMiddleware`, so `request.url.scheme` stays `http`; Starlette `url_for` consults that scheme and builds absolute `http://` URLs for the named `/static` mount. Browsers block these as Mixed Content on the HTTPS page → no CSS/JS.

Verified locally: wrapping a minimal FastAPI app in `ProxyHeadersMiddleware(app, trusted_hosts="*")` flips `url_for('static')` from `http://testserver/static/style.css` to `https://testserver/static/style.css` when `X-Forwarded-Proto: https` is present. SSH-confirmed the live pod runs `uvicorn src.web.app:app --host 0.0.0.0 --port 8010` with no `--proxy-headers`.

## Goals / Non-Goals

- **Goal:** all `url_for('static', ...)` references resolve to `https://` behind Caddy, site-wide.
- **Non-goal:** hardcode relative `/static/...` paths in templates — fragile, loses the named-mount indirection, and must chase every call site (style.css, app.js, generation-panel.js, …). Rejected.

## Design

Single change: `--proxy-headers --forwarded-allow-ips='*'` on both uvicorn commands in `scripts/docker-entrypoint.sh`.

- `--proxy-headers` installs `ProxyHeadersMiddleware`, which reads `X-Forwarded-Proto`/`X-Forwarded-Host`/`X-Forwarded-For` and rewrites `request.url` scheme/host — exactly what `url_for` consults.
- `--forwarded-allow-ips='*'` trusts forwarded headers from any upstream IP. Acceptable here: the pod's `:8010` is cluster-internal only; the sole ingress path is Caddy → NodePort `30820`. The pod is not directly reachable from the public internet, so an attacker cannot bypass Caddy to spoof `X-Forwarded-Proto`.

### Alternatives rejected

- **Hardcode `/static/style.css` (etc.) in templates:** fixes one symptom per edit, loses `url_for`'s named-mount resolution, and any *future* `url_for('static')` silently regresses to Mixed Content. Reverted; the flag is the site-wide fix.

## Risks

- `--forwarded-allow-ips='*'` trusts the proto header from any caller that reaches `:8010`. Mitigated: `:8010` is not publicly exposed; NodePort `30820` fronts Caddy only. If the pod were ever directly addressable publicly, this would need tightening to Caddy's IP.
