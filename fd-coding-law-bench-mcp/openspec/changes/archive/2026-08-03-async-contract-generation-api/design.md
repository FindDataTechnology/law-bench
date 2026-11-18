## Context

**Current State:**
- MCP tools use `anyio.to_thread.run_sync` to wrap sync functions (PostgreSQL via psycopg, file I/O for DOCX/PDF)
- Contract generation is single-threaded per call; batch operations require manual client-side parallelism
- Tag vocabulary loading happens at server startup via `load_vocab_from_db()`
- Clause selection uses synchronous list_clauses with tag filtering

**Constraints:**
- Docx/pdf rendering has no async equivalent; file I/O remains blocking
- PostgreSQL driver is psycopg (sync); upgrading to asyncpg requires connection pool changes
- Backward compatibility: existing sync tools must remain functional

---

## Goals / Non-Goals

**Goals:**
1. Provide true async tool implementations that don't thread-pool block callers
2. Enable batch generation via explicit API rather than client-side loops
3. Support content-first returns (markdown/JSON) without forced file I/O
4. Expose comprehensive tag enumeration with clause coverage metadata

**Non-Goals:**
1. Replace all sync tools (backward compat retained)
2. Async docx/pdf generation (no such ecosystem exists yet)
3. Modify clause extraction pipeline or base templates
4. Real-time streaming responses (batch results return as complete lists)

---

## Decisions

### Decision 1: Hybrid async/sync layering

**Choice:** Implement new tools as native async, but keep internal dependencies sync where appropriate.

**Rationale:**
```python
# New async wrapper pattern
@mcp.tool()
async def contract_content(...):
    def _sync_impl():
        # Sync assembly logic from src.clauses.assemble
        return generate_contract_assembled(...).get("body_text")
    
    # Thread-pool only for the DB-bound part (acceptable bottleneck)
    return await anyio.to_thread.run_sync(_sync_impl)
```

**Alternatives Considered:**
- **Pure async (asyncpg):** Higher complexity, requires connection pool upgrade, migration risk → Deferred to v2
- **Full rewrite in async:** Too much scope for MVP → Rejected

### Decision 2: Content-only path vs file-based dual return

**Choice:** `generate_contract_assembled` returns `{body_text, slots, instructions}` by default; file paths are optional.

**Implementation:**
```python
def generate_contract_assembled(..., format="docx", ...) -> dict:
    resolved, heuristic, base_sections = _select_clauses(...)
    body = _assemble_body(resolved)  # <- Always compute markdown first
    
    if format != "markdown":  # Only render files if requested
        create_docx(body, str(docx_path), title=zh)
        ...
    
    return {
        "body_text": body,  # <- Always included
        "docx_path": str(docx_path) if docx_path else None,
        "pdf_path": str(pdf_path) if pdf_path else None,
        "slots": slots,
        "instructions": instructions,
        "law_refs": law_refs,
    }
```

**Benefit:** Callers who only need text get it instantly; file I/O is opt-in.

### Decision 3: Batch operation parallelization strategy

**Choice:** Client-initiated parallelism via `contract_generate_batch`, server-side `asyncio.gather`.

**Tool implementation:**
```python
@mcp.tool()
async def contract_generate_batch(
    contract_type: str,
    tag_combinations: list[dict] | None = None,
    enumerate_all: bool = False,
    max_concurrent: int = 5,  # Rate limit server load
) -> list[dict]:
    if enumerate_all:
        tag_combinations = await tag_combinations_list(contract_type)
    
    async def generate_one(tags: dict) -> dict:
        try:
            result = await contract_generate(
                contract_type, tags=tags, format="markdown"
            )
            return {"success": True, "tags": tags, **result}
        except Exception as e:
            return {"success": False, "tags": tags, "error": str(e)}
    
    # Throttled parallelism
    semaphore = asyncio.Semaphore(max_concurrent)
    async def limited_run(tc: dict):
        async with semaphore:
            return await generate_one(tc)
    
    results = await asyncio.gather(*[limited_run(tc) for tc in tag_combinations])
    return results
```

**Why not fully auto-enumerate?** Combinatorial explosion (e.g., 3×6×3×3×3=486 combos for sale) can overload LLM quota or time out → Explicit list preferred; `enumerate_all` warns if >1000.

### Decision 4: Tag enumeration algorithm

**Choice:** Cartesian product + availability filter.

**Algorithm:**
```python
def tag_combinations_list(contract_type: str) -> list[dict]:
    vocab = tag_vocab_for_type(contract_type)  # Universal + type-specific dims
    dims = [k for k in vocab.keys() if k not in ("source",)]  # Exclude source from enum
    
    # Generate all combinations
    import itertools
    dim_values = [(k, v) for k, v in vocab.items() if k not in ("source",)]
    combinations = list(itertools.product(*[v for _, v in dim_values]))
    
    # Enrich with clause availability
    enriched = []
    for combo in combinations:
        combo_dict = dict(zip([k for k, _ in dim_values], combo))
        scenario = combo_dict.get("scenario")
        stance = combo_dict.get("stance")
        
        # Quick clause count check (sync query acceptable here)
        tagged_count = len(list_clauses(contract_type, category="tagged", tags={"scenario": scenario}))
        custom_count = len(list_clauses(contract_type, category="custom", tags={"stance": stance}))
        
        enriched.append({
            "tags": combo_dict,
            "has_tagged_clauses": tagged_count > 0,
            "tagged_clause_ids": [...],
            "has_custom_clauses": custom_count > 0,
        })
    
    return enriched
```

### Decision 5: Catalog caching strategy

**Choice:** In-memory cache keyed by `(contract_type, refresh_timestamp)` with 5-minute TTL.

**Implementation:**
```python
from functools import lru_cache
from datetime import datetime, timedelta

_catalog_cache: dict[str, tuple[list, datetime]] = {}

@lru_cache(maxsize=100)
def get_type_catalog(refresh: bool = False) -> list:
    now = datetime.utcnow()
    if refresh or (_catalog_cache.get(contract_type)[1] < now - timedelta(minutes=5)):
        catalog = _build_catalog()  # DB query + counts
        _catalog_cache[contract_type] = (catalog, now)
    return _catalog_cache[contract_type][0]
```

**Trade-off:** Slight staleness risk (up to 5 min) for reduced DB load.

---

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Thread-pooled sync still blocks event loop | Medium | Acceptable for MVP; async DB upgrade planned for v2 |
| Combinatorial explosion in `enumerate_all=True` | High | Warn if >1000 combos; recommend explicit list |
| Coherence errors in batch cause partial failures | Medium | Per-item error reporting; caller handles retries |
| Cache staleness for clause counts | Low | Explicit refresh param; 5-min TTL conservative |
| Docx rendering still sync bottleneck | Low | File output always opt-in; content-first is default path |

---

## Migration Plan

**Phase 1: Add new tools alongside existing sync ones**
- No breaking changes; both coexist
- Test new tools in staging environment

**Phase 2: Update documentation**
- Document new endpoints with examples
- Deprecation notice for old file-only approach (not removal)

**Phase 3: Optional async DB layer**
- If performance gains warrant it, upgrade to asyncpg
- Connection pool change requires minimal surface impact

---

## Open Questions

1. **What's the right `max_concurrent` throttling value?** 5 seems reasonable; monitor error rates during load testing.
2. **Should we support chunked/batched responses for huge enumerations?** Likely unnecessary given typical use case (<100 combinations).
3. **Do we need request IDs for tracing batch failures?** Yes, add `trace_id` to response for debugging; can be auto-generated UUID.
