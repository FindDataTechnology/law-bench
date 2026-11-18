## Why

After logging in, authenticated pages on `lawbench.token118.com` render as bare HTML — no CSS/JS. Root cause: uvicorn runs behind the Caddy TLS-terminating reverse proxy **without** `--proxy-headers`, so it ignores Caddy's `X-Forwarded-Proto: https`. Starlette's `url_for('static', ...)` then builds absolute `http://lawbench.token118.com/static/...` URLs, which browsers block as Mixed Content on the HTTPS page. Every `url_for` static reference (`style.css`, `app.js`, `generation-panel.js`) is affected.

## What Changes

- Add `--proxy-headers --forwarded-allow-ips='*'` to **both** uvicorn launch lines in `scripts/docker-entrypoint.sh` (origin `src.web.app` and public `src.web.public_app`). This installs uvicorn's `ProxyHeadersMiddleware`, which trusts Caddy's forwarded proto/host headers so `url_for` emits scheme-correct `https://` URLs. Site-wide fix — no template edits needed.

## Capabilities

### New Capabilities
- `web-static-assets`: Static assets (CSS/JS) referenced via `url_for('static', ...)` must resolve to scheme-correct URLs when served behind a TLS-terminating reverse proxy, so they are not Mixed-Content-blocked on HTTPS pages.

### Modified Capabilities
<!-- none — this is a deployment-config fix restoring always-intended rendering behavior -->

## Impact

- `scripts/docker-entrypoint.sh` (both uvicorn exec lines).
- Deploy: image rebuild + roll. No template, route, auth, or DB changes.
