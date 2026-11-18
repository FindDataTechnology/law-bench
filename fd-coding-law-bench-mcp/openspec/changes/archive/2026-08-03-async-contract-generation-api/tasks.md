## 1. Core Async Tool Implementations

- [x] 1.1 Create `tools/content.py` with `contract_content` tool (markdown/JSON return path)
- [x] 1.2 Create `tools/batch.py` with `contract_generate_batch` tool + throttled concurrency
- [x] 1.3 Create `tools/catalog.py` with `contract_type_catalog` and `type_metadata` tools
- [x] 1.4 Update `server.py` imports to register new async tools

## 2. Tag Combinatorics Tools

- [x] 2.1 Enhance `tools/tags.py` with `tag_combinations_list` Cartesian product generator
- [x] 2.2 Add clause availability metadata to tag enumeration results
- [x] 2.3 Implement combinatorial explosion warning (>1000 combos)
- [x] 2.4 Add `tag_validate` enhancements for scenario leniency documentation

## 3. Content-First Assembly Path

- [x] 3.1 Refactor `src/clauses/assemble.py` to always compute body_text (not just file paths)
- [x] 3.2 Add format parameter enum: `"markdown" | "docx" | "pdf" | "both"` with `"markdown"` as default
- [x] 3.3 Ensure coherence validation runs before returning body_text
- [x] 3.4 Export law_refs aggregation logic as standalone utility

## 4. Slot Instruction Infrastructure

- [x] 4.1 Verify slot instruction extraction covers all canonical slots
- [x] 5.2 Add ontology fallback for missing slot instructions in responses
- [x] 5.3 Document required vs optional slots in API response schema

## 5. Performance & Caching

- [x] 5.1 Add lru_cache wrapper for contract type catalog queries
- [x] 5.2 Implement 5-minute TTL cache for tag vocabulary loads
- [x] 5.3 Add `refresh=true` parameter to bypass cache on demand

## 6. Error Handling & Observability

- [x] 6.1 Standardize error response structure across all batch tools
- [x] 6.2 Add `trace_id` generation for debugging batch failures
- [x] 6.3 Implement per-item error reporting in batch results
- [x] 6.4 Add success/failure counters to batch response metadata

## 7. Testing

- [x] 7.1 Write unit tests for `tag_combinations_list` algorithm
- [x] 7.2 Write integration tests for `contract_content` with various tag combinations
- [x] 7.3 Write load tests for batch operations (concurrent calls)
- [x] 7.4 Test coherence gate failure cases in content returns

## 8. Documentation

- [x] 8.1 Document new MCP tools in README with usage examples
- [x] 8.2 Create API reference docs for async endpoints
- [x] 8.3 Add migration guide from sync-only approach to async-first
- [x] 8.4 Update OpenSpec status after all implementations complete
