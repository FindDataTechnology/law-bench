# web-static-assets

## Purpose
Static assets (CSS, JS) referenced via `url_for('static', ...)` in templates must resolve to URLs whose scheme matches the client-facing request, so that on an HTTPS page they are not blocked by the browser as Mixed Content.

## Requirements

### Requirement: Reverse-proxy scheme passthrough
When the app is served behind a TLS-terminating reverse proxy that forwards `X-Forwarded-Proto`, the ASGI server MUST trust that header (and `X-Forwarded-Host`) so that `url_for('static', ...)` emits URLs with the forwarded scheme (e.g. `https://`), not the pod-local `http://`.

#### Scenario: Forwarded HTTPS is honored

- **WHEN** a request reaches the app through the reverse proxy with `X-Forwarded-Proto: https`
- **THEN** absolute URLs built by `url_for` (static assets, redirects built from the request URL) use the `https` scheme

#### Scenario: Direct pod access unchanged

- **WHEN** a request reaches the app directly with no forwarded headers
- **THEN** URL building keeps the pod-local `http` scheme (no behavior change for direct access)

### Requirement: Applies to both app factories
The proxy-header trust MUST be configured for the origin app (`src.web.app`) **and** the public read-only app (`src.web.public_app`), since both are served behind the same reverse-proxy posture from the same image (`scripts/docker-entrypoint.sh` selects the factory by `PUBLIC_API`).

#### Scenario: Both launch lines carry the flags

- **WHEN** the container entrypoint starts either app factory
- **THEN** the uvicorn launch line includes `--proxy-headers --forwarded-allow-ips='*'`, so proxy-header trust does not depend on which factory serves the request

### Requirement: No Mixed-Content static references on HTTPS pages
After the fix, an authenticated fetch of any HTML page on `https://lawbench.finddatatech.cloud` MUST contain only `https://` (or scheme-relative/relative) `src`/`href` references to `/static/*` assets — never `http://`.

#### Scenario: Authenticated page carries only https asset references

- **WHEN** an authenticated HTML page is fetched from `https://lawbench.finddatatech.cloud`
- **THEN** every `src`/`href` reference to `/static/*` is `https://` or scheme-relative/relative — never `http://`

#### Scenario: Proxy posture is observable without credentials

- **WHEN** an unauthenticated `/auth/login` request is served over HTTPS
- **THEN** the OIDC redirect target and `redirect_uri` (built from the request's absolute URL) use `https`, demonstrating the forwarded scheme is honored site-wide
