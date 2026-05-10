"""TMDB API endpoints for configuration and testing."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional
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


class CacheConfigInput(BaseModel):
    """Cache configuration input."""
    ttl_days: Optional[int] = None
    cleanup_days: Optional[int] = None
    batch_size: Optional[int] = None
    max_concurrent: Optional[int] = None
    rate_limit: Optional[int] = None
    enable_cache: Optional[bool] = None
    enable_rate_limiting: Optional[bool] = None


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


@router.get("/cache/stats")
async def get_cache_stats(request: Request) -> Dict[str, Any]:
    """Get TMDB cache statistics."""
    if not settings.tmdb_configured:
        raise HTTPException(status_code=400, detail="TMDB not configured")
    
    try:
        service = TMDBService(settings.tmdb_api_key, settings.data_dir)
        stats = service.get_cache_stats()
        return stats
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cache")
async def clear_cache(full_clear: bool = False) -> Dict[str, Any]:
    """Clear TMDB cache.
    
    Args:
        full_clear: If True, clears all cache entries. If False, only clears old entries (>90 days).
    """
    if not settings.tmdb_configured:
        raise HTTPException(status_code=400, detail="TMDB not configured")
    
    try:
        service = TMDBService(settings.tmdb_api_key, settings.data_dir)
        result = await service.clear_cache(full_clear=full_clear)
        return result
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cache/clean")
async def clean_old_cache(max_age_days: Optional[int] = None) -> Dict[str, Any]:
    """Clean old cache entries.
    
    Args:
        max_age_days: Age threshold in days (defaults to settings.cache_cleanup_days)
    """
    if not settings.tmdb_configured:
        raise HTTPException(status_code=400, detail="TMDB not configured")
    
    try:
        service = TMDBService(settings.tmdb_api_key, settings.data_dir)
        age_days = max_age_days or settings.cache_cleanup_days
        result = service.clean_old_cache(max_age_days=age_days)
        return result
    except Exception as e:
        logger.error(f"Failed to clean cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cache/warm")
async def warm_cache(collection_ids: Optional[list[int]] = None) -> Dict[str, Any]:
    """Pre-warm cache with popular collections or specified collection IDs."""
    if not settings.tmdb_configured:
        raise HTTPException(status_code=400, detail="TMDB not configured")
    
    try:
        service = TMDBService(settings.tmdb_api_key, settings.data_dir)
        
        if collection_ids:
            # Warm specific collections
            warmed = 0
            for cid in collection_ids[:20]:  # Limit to 20 collections
                collection = await service.get_collection(cid, use_cache=True)
                if collection:
                    warmed += 1
            return {
                "success": True, 
                "message": f"Warmed {warmed} collections",
                "collections_warmed": warmed
            }
        else:
            # TODO: Fetch popular collections from TMDB trending endpoint
            # For now, return info message
            return {
                "success": True,
                "message": "Automatic cache warming not yet implemented. Specify collection IDs to warm.",
                "collections_warmed": 0
            }
    except Exception as e:
        logger.error(f"Failed to warm cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache/config")
async def get_cache_config(request: Request) -> Dict[str, Any]:
    """Get current cache configuration."""
    return {
        "cache_ttl_days": settings.cache_ttl_days,
        "cache_cleanup_days": settings.cache_cleanup_days,
        "batch_size": settings.batch_size,
        "max_concurrent_api_calls": settings.max_concurrent_api_calls,
        "api_rate_limit": settings.api_rate_limit,
        "enable_cache": settings.enable_cache,
        "enable_rate_limiting": settings.enable_rate_limiting
    }


@router.post("/cache/config")
async def update_cache_config(data: CacheConfigInput, request: Request) -> Dict[str, Any]:
    """Update cache configuration."""
    try:
        settings.set_cache_config(
            ttl_days=data.ttl_days,
            cleanup_days=data.cleanup_days,
            batch_size=data.batch_size,
            max_concurrent=data.max_concurrent,
            rate_limit=data.rate_limit,
            enable_cache=data.enable_cache,
            enable_rate_limiting=data.enable_rate_limiting
        )
        
        logger.info("Cache configuration updated")
        return {
            "success": True,
            "message": "Cache configuration saved",
            "config": await get_cache_config(request)
        }
    except Exception as e:
        logger.error(f"Failed to update cache config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rate-limit/status")
async def get_rate_limit_status(request: Request) -> Dict[str, Any]:
    """Get current rate limiter status (requires active TMDB service)."""
    if not settings.tmdb_configured:
        raise HTTPException(status_code=400, detail="TMDB not configured")
    
    try:
        service = TMDBService(settings.tmdb_api_key, settings.data_dir)
        # Access rate limiter stats (adding property to service would be better)
        return {
            "enabled": settings.enable_rate_limiting,
            "max_calls_per_second": settings.api_rate_limit,
            "session_api_calls": service._stats.get("api_calls", 0),
            "rate_limit_waits": service._stats.get("rate_limit_waits", 0)
        }
    except Exception as e:
        logger.error(f"Failed to get rate limit status: {e}")
        raise HTTPException(status_code=500, detail=str(e))