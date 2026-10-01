"""Tag management API routes."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..schemas import (
    TagCombinationInfo,
    TagCombinationsResponse,
    TagValidateRequest,
    TagValidateResponse,
)
# Module-level imports so the tools are patchable in tests.
# The MCP tools manage their own DB connections internally.
from ...tools.tags import tag_combinations_list, tag_validate

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ============================================================================
# Tag Combination Enumeration
# ============================================================================

@router.get("/combinations/{contract_type}", response_model=TagCombinationsResponse)
async def list_tag_combinations(
    contract_type: str,
    filter_by_clause_coverage: bool = Query(
        default=False,
        description="Filter combinations to only those with clause coverage"
    ),
):
    """List all valid tag combinations for a contract type.

    Returns the Cartesian product of all tag dimensions for the given
    contract type, with metadata about clause availability.

    Warning: If the number of combinations exceeds 1000, a
    combinatorial_warning flag will be set in the response.
    """
    try:
        result = await tag_combinations_list(
            contract_type=contract_type,
            filter_by_clause_coverage=filter_by_clause_coverage,
        )
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


# ============================================================================
# Tag Validation
# ============================================================================

@router.post("/validate", response_model=TagValidateResponse)
async def validate_tags(request: TagValidateRequest):
    """Validate tags against the controlled vocabulary.

    Checks if the provided tags are valid for the given contract type
    according to the tag vocabulary rules. Returns cleaned tags and
    any validation errors.
    """
    try:
        cleaned_tags = await tag_validate(
            tags=request.tags,
            contract_type=request.contract_type,
        )
        return {
            "valid": True,
            "cleaned_tags": cleaned_tags,
            "errors": [],
        }
    except ValueError as e:
        # Validation error - return errors but don't raise HTTP exception
        return {
            "valid": False,
            "cleaned_tags": {},
            "errors": [str(e)],
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": type(e).__name__,
                "message": str(e),
            },
        )
