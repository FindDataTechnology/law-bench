# law-semantic-search Specification

## Purpose

Gives the drafting pipeline retrieval over the 法规库 corpus through its public metered API (law-api), with a configuration surface and degradation behavior that keep law-bench fully decoupled from the law library's vector internals (Qdrant, embedding models, dimensions).

## Requirements

### Requirement: law-api client configuration

The system SHALL configure law search via three environment variables: `LAW_API_BASE_URL` (default `https://law-api.finddatatech.cloud/v1`), `LAW_API_KEY` (APISIX key; empty disables the feature), and `LAW_SEARCH_ENABLED` (default off). law-bench SHALL NOT require any embedding model, vector dimension, or Qdrant address configuration: all vector internals stay behind the API.

#### Scenario: Feature disabled by default

- **WHEN** `LAW_API_KEY` is unset or `LAW_SEARCH_ENABLED` is false
- **THEN** the law search tool is not registered with the drafter and no law-api request is ever made

#### Scenario: Key and base URL are configurable

- **WHEN** the gateway address or key changes via environment
- **THEN** subsequent law search requests use the new values without code changes

### Requirement: law_search drafter tool

The system SHALL provide a `law_search` tool available to the drafter crew (alongside the existing `contract_search`), which sends the drafting query to `POST /v1/search` and returns formatted context chunks, each carrying the law's title, `law_status`, and law_id from the response payload, so the drafter can cite laws with current validity visible.

#### Scenario: Semantic search returns current-status context

- **WHEN** the drafter invokes `law_search` with query `民法典 离婚后子女抚养费` and the gateway is reachable with a valid key
- **THEN** the tool returns ranked law chunks formatted with title, law_status, and law_id per hit

#### Scenario: Empty result is not an error

- **WHEN** a search matches nothing
- **THEN** the tool returns an empty string without raising

### Requirement: Graceful degradation

Any law-api failure (network error, timeout, non-2xx status including 401/429) SHALL degrade silently: the tool returns an empty string and drafting proceeds without law retrieval. The failure SHALL be logged, and no exception SHALL propagate into the crew or pipeline.

#### Scenario: Gateway unreachable

- **WHEN** law-api is unreachable during a drafting run
- **THEN** the drafter completes the run using its other tools, and the outage is visible only in logs

#### Scenario: Rate limit under concurrent evaluation

- **WHEN** a burst of drafting/evaluation requests exceeds the gateway's rate limit
- **THEN** throttled requests degrade to empty results rather than failing the run, and the client does not retry aggressively

### Requirement: law_id treated as an opaque string

All law_id values received from law-api SHALL be handled as opaque strings without numeric coercion; joining law-api results with local data (e.g. the catalog replica) SHALL use explicit, documented comparison semantics.

#### Scenario: law_id with numeric appearance survives round-trip

- **WHEN** a response contains `law_id: "1048577"` and the result is stored or joined locally
- **THEN** the value is preserved as the string `"1048577"` and no component parses it into an integer for matching

### Requirement: Full-text law retrieval

The system SHALL fetch a law's assembled full text and status via `GET /v1/laws/{law_id}` for consumers that need the whole statute (e.g. article-level citation resolution), subject to the same degradation rules.

#### Scenario: Fetch full text by law_id

- **WHEN** a consumer requests law `"123"` via the client and the gateway is up
- **THEN** the client returns the law's assembled full text with its law_status
