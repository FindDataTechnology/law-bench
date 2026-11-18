# contract-artifact-storage Delta

## ADDED Requirements

### Requirement: Fail-fast MinIO endpoint configuration

The system SHALL validate at startup (settings import / app boot) that the MinIO endpoint configuration is a full URL with an explicit `http://` or `https://` scheme: the `minio_host` environment variable, and the `MINIO_PUBLIC_HOST` override when it is set. A value that is empty, or that lacks a URL scheme (e.g. `file.token118.com` instead of `https://file.token118.com`), SHALL be rejected with a configuration error that names the offending environment variable and its value. The system SHALL NOT start with such a value (fail-closed), and artifact upload/download SHALL never fail later at request time solely because the endpoint string was unparseable. An unset `MINIO_PUBLIC_HOST` SHALL remain valid (it falls back to the origin `minio_host`), and a valid `MINIO_PUBLIC_HOST` SHALL NOT require `minio_host`-style fallback semantics beyond scheme presence.

#### Scenario: Scheme-less minio_host is rejected at startup

- **WHEN** the app starts with `minio_host=file.token118.com` (no URL scheme)
- **THEN** startup raises a `ConfigError` whose message names `minio_host` and shows the offending value

#### Scenario: Scheme-less MINIO_PUBLIC_HOST override is rejected at startup

- **WHEN** the app starts with `minio_host=https://file.token118.com` but `MINIO_PUBLIC_HOST=file.token118.com` (no scheme)
- **THEN** startup raises a `ConfigError` whose message names `MINIO_PUBLIC_HOST` and shows the offending value

#### Scenario: Full-URL endpoints boot normally

- **WHEN** the app starts with `minio_host=https://file.token118.com` (and `MINIO_PUBLIC_HOST` unset or a full URL)
- **THEN** settings import succeeds, `MINIO_ENDPOINT` is the URL's `host:port`, and `MINIO_SECURE` reflects the `https` scheme

#### Scenario: Unset MINIO_PUBLIC_HOST remains valid

- **WHEN** the app starts with `MINIO_PUBLIC_HOST` unset and `minio_host` a full URL
- **THEN** no configuration error is raised and the public-endpoint settings fall back to the origin `MINIO_*` values
