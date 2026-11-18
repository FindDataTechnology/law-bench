"""Health check endpoint."""
from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Liveness probe — returns 200 if the server is running."""
    return {"status": "healthy", "service": "contract-review-agent"}
