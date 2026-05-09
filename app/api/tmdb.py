"""TMDB API endpoints for configuration and testing."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any
import logging

from app.services.tmdb_service import TMDBService
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tmdb", tags=["tmdb"])


class TMDBConfigInput(BaseModel):
    """TMDB configuration input."""
    api_key: str


class TMDBTestInput(BaseModel):
    """Test connection input."""
    api_key: str


@router.post("/test")
async def test_connection(data: TMDBTestInput) -> Dict[str, Any]:
    """Test connection to TMDB with API key."""
    try:
        service = TMDBService(data.api_key)
        success, message = await service.test_connection()
        if success:
            return {"success": True, "message": message}
        else:
            return {"success": False, "message": message}
    except Exception as e:
        logger.error(f"TMDB test failed: {e}")
        return {"success": False, "message": str(e)}


@router.post("/config")
async def save_config(data: TMDBConfigInput, request: Request) -> Dict[str, Any]:
    """Save TMDB configuration to persistent storage."""
    # Test connection first
    try:
        service = TMDBService(data.api_key)
        success, message = await service.test_connection()
        if not success:
            return {"success": False, "message": f"Connection failed: {message}"}
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}
    
    # Save to persistent settings
    settings.set_tmdb_config(data.api_key)
    
    # Also store in app state for current session
    request.app.state.tmdb_api_key = data.api_key
    request.app.state.tmdb_configured = True
    
    logger.info("TMDB API key saved")
    return {"success": True, "message": "TMDB API key saved"}


@router.get("/config")
async def get_config(request: Request) -> Dict[str, Any]:
    """Get current TMDB configuration."""
    return {
        "configured": settings.tmdb_configured,
        "api_key": "[REDACTED]" if settings.tmdb_api_key else ""
    }