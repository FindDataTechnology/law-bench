## ADDED Requirements

### Requirement: Optional API key authentication

The system SHALL support optional API key authentication via `X-API-Key` header or `api_key` query parameter.

#### Scenario: API key validation
- **WHEN** `API_KEY_ENABLED=true` and client sends request with valid `X-API-Key` header
- **THEN** request is authenticated and processed normally

#### Scenario: Missing API key
- **WHEN** `API_KEY_ENABLED=true` and client sends request without API key
- **THEN** response is `401 Unauthorized` with error `{"type": "AuthenticationError", "message": "API key required"}`

#### Scenario: Invalid API key
- **WHEN** client sends invalid API key
- **THEN** response is `403 Forbidden` with error `{"type": "AuthenticationError", "message": "Invalid API key"}`

#### Scenario: Authentication disabled
- **WHEN** `API_KEY_ENABLED=false` (default for development)
- **THEN** all requests are allowed without authentication


### Requirement: API key configuration via environment variables

The system SHALL load API keys from environment variables at startup.

#### Scenario: Single API key
- **WHEN** `API_KEYS="key1,key2,key3"` is set
- **THEN** any of those keys are accepted

#### Scenario: API key storage
- **WHEN** server starts
- **THEN** API keys are loaded into memory (hashed for security) and not logged


### Requirement: Public endpoints without authentication

The system SHALL allow certain endpoints to be accessed without authentication.

#### Scenario: Health check is public
- **WHEN** client sends `GET /health`
- **THEN** request succeeds regardless of authentication status

#### Scenario: OpenAPI docs are public
- **WHEN** client accesses `/docs` or `/redoc`
- **THEN** documentation is accessible without API key

#### Scenario: Configurable public paths
- **WHEN** `PUBLIC_ENDPOINTS=["/health", "/docs", "/redoc"]` is set
- **THEN** those paths bypass authentication
