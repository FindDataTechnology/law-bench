## ADDED Requirements

### Requirement: Request rate limiting

The system SHALL enforce request rate limits to prevent abuse and manage server load.

#### Scenario: Rate limit enforcement
- **WHEN** client exceeds configured rate limit (e.g., 100 requests/minute)
- **THEN** response is `429 Too Many Requests` with `Retry-After` header and error `{"type": "RateLimitError", "message": "Rate limit exceeded"}`

#### Scenario: Rate limit headers
- **WHEN** client sends request within rate limit
- **THEN** response includes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers

#### Scenario: Per-client rate limiting
- **WHEN** rate limiting is enabled
- **THEN** limits are tracked per API key (if authenticated) or per IP address (if not)


### Requirement: Configurable rate limits

The system SHALL support configurable rate limits via environment variables.

#### Scenario: Global rate limit configuration
- **WHEN** `RATE_LIMIT_REQUESTS=100` and `RATE_LIMIT_WINDOW=60` are set
- **THEN** system allows 100 requests per 60-second window per client

#### Scenario: Endpoint-specific rate limits
- **WHEN** `RATE_LIMIT_BATCH=10` is set (lower limit for expensive batch operations)
- **THEN** `/contracts/batch` endpoint has stricter limit than other endpoints

#### Scenario: Rate limit disabled
- **WHEN** `RATE_LIMIT_ENABLED=false`
- **THEN** no rate limiting is enforced (useful for development/testing)


### Requirement: Rate limit storage

The system SHALL use in-memory storage for rate limit counters with optional Redis backend.

#### Scenario: In-memory rate limiting (default)
- **WHEN** `RATE_LIMIT_BACKEND=memory` (default)
- **THEN** rate limits are tracked in process memory (fast, but not shared across workers)

#### Scenario: Redis-backed rate limiting
- **WHEN** `RATE_LIMIT_BACKEND=redis` and `REDIS_URL` is configured
- **THEN** rate limits are shared across multiple server instances via Redis

#### Scenario: Rate limit counter reset
- **WHEN** rate limit window expires
- **THEN** counter resets automatically for that client
