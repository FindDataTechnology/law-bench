# web-static-assets

## Purpose
Static assets (CSS, JS) referenced via `url_for('static', ...)` in templates must resolve to URLs whose scheme matches the client-facing request, so that on an HTTPS page they are not blocked by the browser as Mixed Content.

## Requirements

### REQ1 Reverse-proxy scheme passthrough
When the app is served behind a TLS-terminating reverse proxy that forwards `X-Forwarded-Proto`, the ASGI server MUST trust that header (and `X-Forwarded-Host`) so that `url_for('static', ...)` emits URLs with the forwarded scheme (e.g. `https://`), not the pod-local `http://`.

### REQ2 Applies to both app factories
The proxy-header trust MUST be configured for the origin app (`src.web.app`) **and** the public read-only app (`src.web.public_app`), since both are served behind the same reverse-proxy posture from the same image (`scripts/docker-entrypoint.sh` selects the factory by `PUBLIC_API`).

### REQ3 No Mixed-Content static references on HTTPS pages
After the fix, an authenticated fetch of any HTML page on `https://lawbench.token118.com` MUST contain only `https://` (or scheme-relative/relative) `src`/`href` references to `/static/*` assets — never `http://`.
