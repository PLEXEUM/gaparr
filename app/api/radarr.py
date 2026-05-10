"""Radarr API endpoints for configuration and testing."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging

from app.services.radarr_service import RadarrClient
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/radarr", tags=["radarr"])


class RadarrConfigInput(BaseModel):
    """Radarr configuration input."""
    url: str
    api_key: str
    root_folder: str


class RadarrTestInput(BaseModel):
    """Test connection input."""
    url: str
    api_key: str


@router.post("/test")
async def test_connection(data: RadarrTestInput) -> Dict[str, Any]:
    """Test connection to Radarr."""
    try:
        client = RadarrClient(data.url, data.api_key)
        success, message = await client.test_connection()
        if success:
            return {"success": True, "message": message}
        else:
            return {"success": False, "message": message}
    except Exception as e:
        logger.error(f"Radarr test failed: {e}")
        return {"success": False, "message": str(e)}


@router.post("/config")
async def save_config(data: RadarrConfigInput, request: Request) -> Dict[str, Any]:
    """Save Radarr configuration to persistent storage."""
    # Test connection first
    try:
        client = RadarrClient(data.url, data.api_key)
        success, message = await client.test_connection()
        if not success:
            return {"success": False, "message": f"Connection failed: {message}"}
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}
    
    # Save to persistent settings
    settings.set_radarr_config(data.url, data.api_key, data.root_folder)
    
    # Also store in app state for current session
    request.app.state.radarr_url = data.url
    request.app.state.radarr_api_key = data.api_key
    request.app.state.root_folder_path = data.root_folder
    request.app.state.radarr_configured = True
    
    logger.info(f"Radarr configuration saved: {data.url}")
    return {"success": True, "message": "Radarr configuration saved"}


@router.get("/config")
async def get_config(request: Request) -> Dict[str, Any]:
    """Get current Radarr configuration."""
    return {
        "configured": settings.radarr_configured,
        "url": settings.radarr_url,
        "api_key": "[REDACTED]" if settings.radarr_api_key else "",
        "root_folder": settings.root_folder_path
    }


@router.get("/root-folders")
async def get_root_folders(request: Request) -> List[Dict[str, Any]]:
    """Fetch root folders from Radarr."""
    url = settings.radarr_url
    api_key = settings.radarr_api_key
    
    if not url or not api_key:
        raise HTTPException(status_code=400, detail="Radarr not configured")
    
    try:
        client = RadarrClient(url, api_key)
        folders = await client.get_root_folders()
        return folders
    except Exception as e:
        logger.error(f"Failed to fetch root folders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/check-collections")
async def check_collections(request: Request) -> Dict[str, Any]:
    """Check if Radarr provides collection data natively."""
    url = settings.radarr_url
    api_key = settings.radarr_api_key
    
    if not url or not api_key:
        raise HTTPException(status_code=400, detail="Radarr not configured")
    
    try:
        client = RadarrClient(url, api_key)
        result = await client.get_movies_with_collections()
        # Return summary instead of all movies
        sample = result[0] if result else {}
        return {
            "total_movies": len(result),
            "sample_keys": list(sample.keys()) if sample else [],
            "has_collectionTmdbId": 'collectionTmdbId' in sample if sample else False
        }
    except Exception as e:
        logger.error(f"Failed to check collections: {e}")
        raise HTTPException(status_code=500, detail=str(e))