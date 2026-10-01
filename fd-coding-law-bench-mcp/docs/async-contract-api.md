# Async Contract Generation API

New async-native MCP tools for high-performance contract generation with tag-driven assembly.

## Overview

This API provides:
- **Content-first returns**: Get contract markdown/JSON instantly without file I/O
- **Batch generation**: Generate multiple contracts in parallel with throttling
- **Tag enumeration**: Discover all valid tag combinations for any contract type
- **Comprehensive metadata**: Contract type catalogs with clause coverage stats

## New Tools

### `contract_content`

Return assembled contract content (markdown/JSON) without file I/O.

**Parameters:**
- `contract_type` (str): Contract class key (e.g., `"sale"`, `"employment"`)
- `tags` (dict, optional): Tag dict with `scenario` and/or `stance`
- `stance` (str, optional): Convenience for `tags["stance"]`
- `format` (str): `"markdown"` (default), `"docx"`, `"pdf"`, or `"both"`
- `include_current_tags` (bool): Attach live tag vocabulary
- `trace_id` (str, optional): Debugging trace ID

**Returns:**
```python
{
    "trace_id": "uuid",
    "contract_type": "sale",
    "format": "markdown",
    "body_text": "## 当事人\n\n甲方...",
    "slots": ["party_a", "party_b", ...],
    "instructions": [{"name": "party_a", "label": "甲方名称", ...}],
    "law_refs": [{"name": "民法典", "category": "statute", ...}],
    "tags_used": {"scenario": "农产品买卖", "stance": "balanced"}
}
```

**Example:**
```python
result = await contract_content(
    "sale",
    tags={"scenario": "农产品买卖", "stance": "balanced"},
    format="markdown"
)
print(result["body_text"])  # Instant markdown return
```

---

### `contract_generate_batch`

Generate multiple contracts in parallel across different tag combinations.

**Parameters:**
- `contract_type` (str): Contract class key
- `tag_combinations` (list[dict], optional): Explicit list of tag dicts
- `enumerate_all` (bool): Auto-generate all valid combinations (warns if >1000)
- `max_concurrent` (int): Throttle limit (default 5)

**Returns:**
```python
{
    "trace_id": "uuid",
    "contract_type": "sale",
    "total_requested": 6,
    "success_count": 5,
    "failure_count": 1,
    "results": [
        {
            "success": True,
            "tags": {"scenario": "农产品买卖", "stance": "pro_a"},
            "body_text": "...",
            "slots": [...],
            ...
        },
        {
            "success": False,
            "tags": {"scenario": "invalid", "stance": "pro_b"},
            "error": {
                "type": "CoherenceError",
                "message": "Missing required slot: party_a",
                "details": {}
            }
        }
    ],
    "combinatorial_warning": False
}
```

**Example:**
```python
# Explicit combinations
result = await contract_generate_batch(
    "sale",
    tag_combinations=[
        {"scenario": "农产品买卖", "stance": "balanced"},
        {"scenario": "消费品零售", "stance": "pro_a"}
    ],
    max_concurrent=3
)

# Auto-enumerate (use cautiously!)
result = await contract_generate_batch("sale", enumerate_all=True)
```

---

### `tag_combinations_list`

Enumerate all valid tag combinations for a contract type with clause availability metadata.

**Parameters:**
- `contract_type` (str): Contract class key
- `include_clause_availability` (bool): Enrich with clause counts (default True)
- `filter_by_clause_coverage` (bool): Exclude combos with no tagged clauses

**Returns:**
```python
{
    "contract_type": "sale",
    "dimensions": ["stance", "scenario"],
    "combinations": [
        {
            "tags": {"stance": "pro_a", "scenario": "农产品买卖"},
            "has_tagged_clauses": True,
            "tagged_clause_count": 3,
            "tagged_clause_ids": [7094, 7095, 7096],
            "has_custom_clauses": True
        },
        ...
    ],
    "estimated_combinations": 18,
    "combinatorial_warning": False
}
```

**Example:**
```python
result = await tag_combinations_list("sale", include_clause_availability=True)
for combo in result["combinations"]:
    print(f"{combo['tags']} -> {combo['tagged_clause_count']} tagged clauses")
```

---

### `contract_type_catalog`

List all supported contract types with metadata.

**Parameters:**
- `include_clause_counts` (bool): Include per-type clause statistics (default True)
- `refresh` (bool): Bypass cache (default False)

**Returns:**
```python
[
    {
        "key": "sale",
        "zh_name": "买卖合同",
        "slot_count": 12,
        "total_base_clauses": 10,
        "total_tagged_clauses": 5,
        "total_custom_clauses": 3,
        "has_scenarios": True
    },
    ...
]
```

**Example:**
```python
catalog = await contract_type_catalog(include_clause_counts=True)
for t in catalog:
    print(f"{t['zh_name']} ({t['key']}): {t['slot_count']} slots, {t['total_base_clauses']} base clauses")
```

---

### `type_metadata`

Get detailed metadata for a single contract type.

**Parameters:**
- `contract_type` (str): Contract class key
- `include_scenario_details` (bool): Include per-scenario clause counts (default True)

**Returns:**
```python
{
    "key": "sale",
    "zh_name": "买卖合同",
    "slot_count": 12,
    "universal_dims": {
        "stance": ["pro_a", "pro_b", "balanced"],
        "strength": ["strong", "standard", "mild"],
        ...
    },
    "type_specific_dims": {
        "risk_transfer_node": ["on_delivery", "at_port_of_shipment", ...],
        ...
    },
    "scenarios": [
        {
            "name": "农产品买卖",
            "clause_count": 3,
            "has_tagged_clauses": True,
            "example_clause_ids": [7094, 7095, 7096]
        },
        ...
    ],
    "assembly_ready": True
}
```

**Example:**
```python
meta = await type_metadata("sale", include_scenario_details=True)
print(f"Scenarios: {[s['name'] for s in meta['scenarios']]}")
```

---

## Caching

All read-only tools use 5-minute TTL caches to reduce DB load:
- `tag_vocab_list`: Cached by contract_type
- `contract_type_catalog`: Global cache
- `type_metadata`: No cache (always fresh)

Pass `refresh=True` to bypass cache on demand.

## Error Handling

All tools return standardized error responses:
```python
{
    "success": False,
    "trace_id": "uuid",
    "error": {
        "type": "CoherenceError",
        "message": "Missing required slot: party_a",
        "details": {"slot": "party_a"}
    }
}
```

Batch operations include per-item error reporting with trace IDs for debugging.

## Performance

- **Content-first path** (`format="markdown"`): <50ms typical (no file I/O)
- **Batch operations**: Throttled via semaphore (default 5 concurrent)
- **Tag enumeration**: Cartesian product generation with combinatorial warnings

## Migration from Sync Tools

Existing sync tools (`contract_generate`, `pipeline_run`) remain functional. New async tools provide:
- Faster returns (content-first, no forced file I/O)
- Batch capabilities (parallel generation)
- Better observability (trace IDs, structured errors)

No breaking changes - old code continues to work.
