"""Read-only tag-vocabulary tools.

Wrap :mod:`src.clauses.tags`: ``tag_vocab_list`` exposes the merged flat
vocabulary for a contract type (universal + type-specific dims), and
``tag_validate`` dry-runs a tag dict against the controlled vocabulary. Both
refresh the in-memory ``TAG_VOCAB`` from ``tag_dims`` first (idempotent,
best-effort) so type-specific dims are reflected, mirroring
``contract_generate``'s ``include_current_tags`` path. Neither writes to the
``tag_dims`` table or registers new dimensions.

Caching: ``tag_vocab_list`` uses a 5-minute TTL cache keyed by contract_type.
Pass ``refresh=True`` to bypass cache.
"""

from __future__ import annotations

import anyio
from datetime import datetime, timedelta
from functools import lru_cache

from ..server import mcp


# ponytail: TTL cache for tag vocabularies to reduce DB round-trips
_vocab_cache: dict[str | None, tuple[dict, datetime]] = {}
_CACHE_TTL = timedelta(minutes=5)


def _get_cached_vocab(contract_type: str | None, refresh: bool = False) -> dict:
    """Get tag vocab with TTL cache. Returns cached value if fresh, else recomputes."""
    now = datetime.utcnow()

    if not refresh and contract_type in _vocab_cache:
        cached_value, cached_time = _vocab_cache[contract_type]
        if now - cached_time < _CACHE_TTL:
            return cached_value

    # Recompute and cache
    from src.clauses.tags import load_vocab_from_db, tag_vocab_for_type
    load_vocab_from_db()
    result = tag_vocab_for_type(contract_type)
    _vocab_cache[contract_type] = (result, now)
    return result


@mcp.tool(tags={"tags"})
async def tag_vocab_list(
    contract_type: str | None = None,
    refresh: bool = False,
) -> dict[str, list[str]]:
    """List the merged flat tag vocabulary for a contract type.

    Returns ``{dim: [allowed values]}`` for every dimension valid for the type:
    universal starter dims (``stance`` / ``strength`` / ``risk`` / ``mandatory``)
    merged with the type-specific dims from the ``tag_dims`` table. When
    ``contract_type`` is ``None``, returns only the universal dims.

    Parameters:
        contract_type: contract class key, or ``None`` for universal-only.
        refresh: bypass cache and reload from DB (default False). Results are
            cached for 5 minutes to reduce DB load.

    Read-only: does not write to ``tag_dims`` or register new dimensions.
    """
    def _go() -> dict[str, list[str]]:
        return _get_cached_vocab(contract_type, refresh=refresh)

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"tags"})
async def tag_validate(tags: dict, contract_type: str | None = None) -> dict:
    """Validate a tag dict against the controlled vocabulary.

    Returns the cleaned dict: unknown keys are dropped, and ``scenario`` plus
    free-form dims are kept (any non-empty value). For a controlled dim with an
    invalid value, raises a tool error naming the dim, the bad value, and the
    allowed set.

    Parameters:
        tags: tag dict to validate.
        contract_type: contract class key (selects type-specific controlled
            dims); ``None`` validates against universal dims only.

    Read-only: does not write to ``tag_dims`` or register new dimensions.
    """
    from src.clauses.tags import load_vocab_from_db, validate_tags

    def _go() -> dict:
        load_vocab_from_db()
        return validate_tags(tags, contract_type)

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"tags"})
async def tag_combinations_list(
    contract_type: str,
    include_clause_availability: bool = True,
    filter_by_clause_coverage: bool = False,
) -> dict:
    """Enumerate all valid tag combinations for a contract type.

    Generates Cartesian product of all tag dimensions (excluding ``source``)
    with optional clause availability metadata. Warns if combinations exceed
    1000 due to combinatorial explosion risk.

    Parameters:
        contract_type: contract class key (e.g. ``"sale"``).
        include_clause_availability: when True, enriches each combination with
            ``has_tagged_clauses``, ``tagged_clause_count``, ``has_custom_clauses``
            fields based on actual clause DB queries.
        filter_by_clause_coverage: when True, excludes combinations that have
            no tagged clauses (only base fallback available).

    Returns ``{contract_type, dimensions, combinations: [{tags, has_tagged_clauses,
    tagged_clause_count, has_custom_clauses, tagged_clause_ids}], estimated_combinations,
    combinatorial_warning: bool}``.

    Example:
    ```python
    result = await tag_combinations_list("sale", include_clause_availability=True)
    # result['combinations'] shows each valid tag combo with clause coverage
    ```
    """
    from src.clauses.tags import load_vocab_from_db, tag_vocab_for_type

    def _go() -> dict:
        load_vocab_from_db()
        vocab = tag_vocab_for_type(contract_type)

        # Exclude 'source' from enumeration (it's metadata, not a legal axis)
        dims_to_enum = [k for k in vocab.keys() if k != "source"]
        dim_values = [(k, vocab[k]) for k in dims_to_enum]

        # Cartesian product
        import itertools
        values = [v for _, v in dim_values]
        raw_combos = list(itertools.product(*values))
        combos = [dict(zip(dims_to_enum, combo)) for combo in raw_combos]

        # Enrich with clause availability if requested
        enriched = []
        if include_clause_availability:
            from src.clauses.store import list_clauses

            for combo in combos:
                scenario = combo.get("scenario")
                stance = combo.get("stance")

                # Query tagged clauses by scenario
                tagged_count = 0
                tagged_ids = []
                if scenario:
                    tagged = list_clauses(
                        contract_type,
                        category="tagged",
                        tags={"scenario": scenario}
                    )
                    tagged_count = len(tagged)
                    tagged_ids = [c["id"] for c in tagged]

                # Query custom clauses by stance
                custom_count = 0
                if stance:
                    custom = list_clauses(
                        contract_type,
                        category="custom",
                        tags={"stance": stance}
                    )
                    custom_count = len(custom)

                enriched.append({
                    "tags": combo,
                    "has_tagged_clauses": tagged_count > 0,
                    "tagged_clause_count": tagged_count,
                    "tagged_clause_ids": tagged_ids,
                    "has_custom_clauses": custom_count > 0,
                })
        else:
            # No enrichment, just return raw combos
            enriched = [{"tags": combo} for combo in combos]

        # Apply filter if requested
        if filter_by_clause_coverage:
            enriched = [c for c in enriched if c.get("has_tagged_clauses", False)]

        warned = len(enriched) > 1000

        return {
            "contract_type": contract_type,
            "dimensions": dims_to_enum,
            "combinations": enriched,
            "estimated_combinations": len(enriched),
            "combinatorial_warning": warned,
        }

    return await anyio.to_thread.run_sync(_go)
