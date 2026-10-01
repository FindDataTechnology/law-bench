"""Contract batch generation API - parallel contract generation with throttling.

Wraps contract_content/contract_generate tools with asyncio.gather + semaphore
for controlled concurrent execution. Supports explicit tag list or auto-enumerate.
Includes error handling, trace IDs, and per-item failure reporting.
"""

from __future__ import annotations

import anyio
import uuid
import asyncio
from typing import Any
from functools import lru_cache

from ..server import mcp
from .errors import make_error_response, extract_error_info


# ponytail: in-memory cache for tag enumeration to avoid redundant DB reads
@lru_cache(maxsize=100)
def _cached_tag_combinations(contract_type: str, max_warn: int = 1000) -> dict:
    """Cached tag combinations lookup with combinatorial warning."""
    return None  # computed on-demand below


@mcp.tool(tags={"contracts"})
async def contract_generate_batch(
    contract_type: str,
    tag_combinations: list[dict] | None = None,
    enumerate_all: bool = False,
    max_concurrent: int = 5,
) -> dict:
    """Generate multiple contracts in parallel across different tag combinations.

    Parameters:
        contract_type: contract class key (e.g. ``"sale"``).
        tag_combinations: explicit list of tag dicts to generate, e.g.
            ``[{"scenario": "农产品买卖", "stance": "pro_a"}, {"stance": "pro_b"}]``.
            If None and enumerate_all=False, requires at least one item.
        enumerate_all: if True, auto-generate all valid combinations for the type.
            Warning emitted if >1000 combos due to combinatorial explosion risk.
        max_concurrent: throttle limit for parallel calls (default 5) to protect
            server load and LLM quota.

    Returns:
        ``{trace_id, contract_type, total_requested, success_count, failure_count,
        results: [{success, tags, ...result_or_error}, ...], combinatorial_warning: bool}``

        Each result item includes success flag, requested tags, and either full
        contract content (on success) or error details (on failure).

    Example:
    ```python
    # Explicit combinations
    result = await contract_generate_batch(
        "sale",
        tag_combinations=[
            {"scenario": "农产品买卖", "stance": "balanced"},
            {"scenario": "消费品零售", "stance": "pro_a"}
        ]
    )

    # Auto-enumerate (use cautiously!)
    result = await contract_generate_batch("sale", enumerate_all=True)
    ```
    """
    from src.clauses.tags import tag_vocab_list, validate_tags
    from src.eval.errors import NotFoundError

    # ponytail: combine tag enumeration + validation in single thread hop
    def _prepare_combinations() -> tuple[list[dict], bool]:
        if enumerate_all:
            vocab = tag_vocab_list(contract_type)
            dims_to_enum = [k for k in vocab.keys() if k not in ("source",)]

            # Cartesian product via itertools
            import itertools
            values = [vocab[k] for k in dims_to_enum]
            raw_combos = list(itertools.product(*values))
            combos = [dict(zip(dims_to_enum, combo)) for combo in raw_combos]

            warned = len(combos) > 1000
            return combos, warned

        elif tag_combinations:
            # Validate each combination
            validated = []
            for tc in tag_combinations:
                cleaned = validate_tags(tc, contract_type)
                if cleaned:
                    validated.append(cleaned)
            return validated, False

        else:
            raise ValueError("must provide tag_combinations or set enumerate_all=True")

    trace = str(uuid.uuid4())

    try:
        combinations, combinatorial_warning = _prepare_combinations()
    except Exception as e:
        err = extract_error_info(e)
        return {
            **make_error_response(trace, err["type"], err["message"], err["details"]),
            "contract_type": contract_type,
            "total_requested": 0,
            "success_count": 0,
            "failure_count": 0,
            "results": [],
            "combinatorial_warning": False,
        }

    if combinatorial_warning:
        print(f"[WARNING] Generated {len(combinations)} combinations for {contract_type}. "
              f"Consider providing explicit tag_combinations to reduce load.")

    async def generate_one(tc: dict) -> dict:
        """Single contract generation with error capture."""
        try:
            from .content import contract_content

            result = await contract_content(
                contract_type=contract_type,
                tags=tc,
                format="markdown",  # fast path, no file I/O
                trace_id=f"{trace}:{tc.get('scenario', 'unknown')}:{tc.get('stance', 'none')}",
            )
            return {
                "success": True,
                "tags": tc,
                **result,
            }
        except Exception as e:
            err = extract_error_info(e)
            return {
                "success": False,
                "tags": tc,
                "error": err,
            }

    # Throttled parallelism via semaphore
    semaphore = anyio.Semaphore(max_concurrent)

    async def limited_run(tc: dict):
        async with semaphore:
            return await generate_one(tc)

    results = await asyncio.gather(*[limited_run(tc) for tc in combinations])

    # Compute summary stats
    successes = sum(1 for r in results if r.get("success"))
    failures = len(results) - successes

    return {
        "trace_id": trace,
        "contract_type": contract_type,
        "total_requested": len(combinations),
        "success_count": successes,
        "failure_count": failures,
        "results": results,
        "combinatorial_warning": combinatorial_warning,
    }
