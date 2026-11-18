"""Contract type catalog API - metadata endpoints for all contract types.

Provides comprehensive listing of contract types with slot counts, clause coverage
status, scenario vocabularies, and assembly readiness indicators.

Caching: catalog queries use lru_cache for fast repeated reads. Pass
``refresh=True`` to bypass cache.
"""

from __future__ import annotations

import anyio
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Literal

from ..annotations import annotations_for
from ..server import mcp


# ponytail: TTL cache for catalog queries, keyed by *shape*.
#
# 键必须是 ``include_clause_counts``：两个形状的字段相同但**值不同**（不计数时三个
# 计数恒为 0）。共用一个槽会出现两种错答，且都长得像真数据：
#   - 先 false 后 true → 计数读拿到 5 分钟的假 0（"条款表是空的"）；
#   - 先 true 后 false → 便宜的读拿到计数值（它本来可以不打库）。
# 前者已经误导过一次现网审计（2026-11-10 记「66 个类型计数全 0」＝读路径错位），
# 实际数据是好的；回归锚点见 ``tests/test_catalog_cache_key.py``。
_catalog_cache: dict[bool, tuple[list[dict], datetime]] = {}
_CACHE_TTL = timedelta(minutes=5)


@mcp.tool(tags={"contracts"}, annotations=annotations_for("contract_type_catalog"))
async def contract_type_catalog(
    include_clause_counts: bool = True,
    refresh: bool = False,
) -> list[dict]:
    """List all supported contract types with metadata.

    Parameters:
        include_clause_counts: when True, includes per-type clause statistics
            (base, tagged, custom counts). Slower but more informative.
        refresh: bypass cache and reload from DB (default False). Results are
            cached for 5 minutes to reduce DB load.

    Returns sorted list of ``{key, zh_name, slot_count, total_base_clauses,
    total_tagged_clauses, total_custom_clauses, has_scenarios: bool}``.

    Example:
    ```python
    catalog = await contract_type_catalog(include_clause_counts=True)
    # Returns [{key: 'sale', zh_name: '买卖合同', ..., ...}, ...]
    ```
    """
    from src.contracts.templates import list_contract_types

    def _go() -> list[dict]:
        global _catalog_cache
        now = datetime.utcnow()

        # 按形状查缓存：不计数的那份**不能**拿来回答"要计数"的提问。
        shape = bool(include_clause_counts)
        if not refresh:
            cached = _catalog_cache.get(shape)
            if cached is not None:
                cached_value, cached_time = cached
                if now - cached_time < _CACHE_TTL:
                    return cached_value

        types = list_contract_types()
        result = []

        for t in types:
            key = t["key"]
            zh = t["zh"]

            # ponytail: minimal DB query only when requested
            base_count = 0
            tagged_count = 0
            custom_count = 0

            if include_clause_counts:
                from src.clauses.store import list_clauses

                base_clauses = list_clauses(key, category="base")
                tagged_clauses = list_clauses(key, category="tagged")
                custom_clauses = list_clauses(key, category="custom")

                base_count = len(base_clauses)
                tagged_count = len(tagged_clauses)
                custom_count = len(custom_clauses)

            # Slot count from template registry
            from src.contracts.templates import get_template
            try:
                template = get_template(key)
                slot_count = len(template["slots"])
            except Exception:
                slot_count = 12  # default canonical slots

            result.append({
                "key": key,
                "zh_name": zh,
                "slot_count": slot_count,
                "total_base_clauses": base_count,
                "total_tagged_clauses": tagged_count,
                "total_custom_clauses": custom_count,
                "has_scenarios": tagged_count > 0,
            })

        sorted_result = sorted(result, key=lambda x: x["key"])
        _catalog_cache[shape] = (sorted_result, now)
        return sorted_result

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"contracts"}, annotations=annotations_for("type_metadata"))
async def type_metadata(
    contract_type: str,
    include_scenario_details: bool = True,
) -> dict:
    """Get detailed metadata for a single contract type.

    Parameters:
        contract_type: contract class key (e.g. ``"sale"``).
        include_scenario_details: when True, includes per-scenario clause counts.

    Returns ``{key, zh_name, slot_count, universal_dims, type_specific_dims,
    scenarios: [{name, clause_count, has_tagged_clauses}], assembly_ready: bool}``.

    Example:
    ```python
    meta = await type_metadata("sale", include_scenario_details=True)
    # meta['scenarios'] shows each scenario's clause availability
    ```
    """
    from src.contracts.templates import get_template, list_contract_types
    # 函数真名是 tag_vocab_for_type（tag_vocab_list 是 MCP 侧工具名，不是这里的符号）——
    # 2026-11-10 实测：这行曾写成 tag_vocab_list，导致 type_metadata 一调就 ImportError。
    from src.clauses.tags import tag_vocab_for_type
    from src.eval.errors import NotFoundError

    def _go() -> dict:
        # Find type by key
        types = list_contract_types()
        found = None
        for t in types:
            if t["key"] == contract_type:
                found = t
                break

        if not found:
            raise NotFoundError(f"unknown contract type: {contract_type!r}")

        zh = found["zh"]

        # Get template
        template = get_template(contract_type)
        slot_count = len(template["slots"])

        # Get tag vocabulary
        vocab = tag_vocab_for_type(contract_type)
        universal_dims = {k: v for k, v in vocab.items() if k in ("stance", "strength", "risk", "mandatory")}
        type_specific_dims = {k: v for k, v in vocab.items() if k not in ("stance", "strength", "risk", "mandatory", "source")}

        scenarios = []
        if include_scenario_details and "scenario" in vocab:
            from src.clauses.store import list_clauses

            for scenario_name in vocab.get("scenario", []):
                tagged = list_clauses(contract_type, category="tagged", tags={"scenario": scenario_name})
                scenarios.append({
                    "name": scenario_name,
                    "clause_count": len(tagged),
                    "has_tagged_clauses": len(tagged) > 0,
                    "example_clause_ids": [c["id"] for c in tagged[:3]],  # sample first 3
                })

        # Check assembly readiness (has at least one ready custom clause)
        from src.clauses.tag_review import is_assembly_ready
        from src.clauses.store import list_clauses

        custom = list_clauses(contract_type, category="custom")
        assembly_ready = any(is_assembly_ready(c) for c in custom)

        return {
            "key": contract_type,
            "zh_name": zh,
            "slot_count": slot_count,
            "universal_dims": universal_dims,
            "type_specific_dims": type_specific_dims,
            "scenarios": scenarios,
            "assembly_ready": assembly_ready,
        }

    return await anyio.to_thread.run_sync(_go)
