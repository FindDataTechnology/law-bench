"""Contract generation API routes."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..schemas import (
    ContractBatchRequest,
    ContractBatchResponse,
    ContractContentRequest,
    ContractContentResponse,
    ContractTypeCatalogResponse,
    TypeMetadataResponse,
)
# Module-level imports so the tools are patchable in tests and resolvable once.
# The MCP tools manage their own DB connections internally (via anyio.to_thread
# + psycopg), so no db dependency is injected here. get_db remains available in
# deps.py for future connection-pooling work.
from ...tools.content import contract_content
from ...tools.batch import contract_generate_batch
from ...tools.catalog import contract_type_catalog, type_metadata

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ============================================================================
# Contract Content Generation
# ============================================================================

@router.post("/content", response_model=ContractContentResponse)
async def generate_contract_content(request: ContractContentRequest):
    """Generate contract content from tags.

    This endpoint wraps the MCP contract_content tool, providing HTTP access
    to the tag-driven contract generation system.
    """
    try:
        result = await contract_content(
            contract_type=request.contract_type,
            tags=request.tags,
            format=request.format,
            include_current_tags=request.include_current_tags,
            trace_id=request.trace_id,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(e).__name__,
                "message": str(e),
                "trace_id": request.trace_id,
            },
        )


# ============================================================================
# Batch Contract Generation
# ============================================================================

@router.post("/batch", response_model=ContractBatchResponse)
async def generate_contract_batch(request: ContractBatchRequest):
    """Generate multiple contracts in parallel.

    This endpoint wraps the MCP contract_generate_batch tool, allowing
    batch generation across multiple tag combinations.
    """
    try:
        result = await contract_generate_batch(
            contract_type=request.contract_type,
            tag_combinations=request.tag_combinations,
            enumerate_all=request.enumerate_all,
            max_concurrent=request.max_concurrent,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(e).__name__,
                "message": str(e),
            },
        )


# ============================================================================
# Contract Type Catalog
# ============================================================================

@router.get("/types", response_model=ContractTypeCatalogResponse)
async def list_contract_types():
    """List all available contract types.

    Returns metadata about all contract types including slot counts,
    clause counts, and scenario availability.
    """
    try:
        result = await contract_type_catalog()
        return {
            "types": result,
            "total": len(result),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(e).__name__,
                "message": str(e),
            },
        )


@router.get("/types/{contract_type}", response_model=TypeMetadataResponse)
async def get_contract_type_metadata(contract_type: str):
    """Get detailed metadata for a specific contract type.

    Returns comprehensive information about a contract type including
    tag dimensions, scenarios, and assembly readiness.
    """
    try:
        result = await type_metadata(contract_type=contract_type)
        return result
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NotFound",
                    "message": f"Contract type '{contract_type}' not found",
                },
            )
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(e).__name__,
                "message": str(e),
            },
        )
