"""Sync API endpoints for managing missing movie additions."""

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from app.services.sync_service import SyncService
from app.services.radarr_service import RadarrClient
from app.services.tmdb_service import TMDBService
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


class IgnoreCollectionInput(BaseModel):
    collection_id: int


class IgnoreMovieInput(BaseModel):
    tmdb_id: int


class SyncTriggerInput(BaseModel):
    dry_run: bool = False


class SyncSettingsInput(BaseModel):
    daily_limit: int
    sync_time: str
    hide_future: bool

@router.get("/status")
async def get_sync_status(request: Request) -> Dict[str, Any]:
    """Get current sync status WITHOUT performing a scan."""
    # Check if configured
    if not settings.is_fully_configured:
        return {
            "configured": False,
            "message": "Radarr or TMDB not configured. Please go to Settings.",
            "first_run": settings.first_run
        }
    
    # Only return configuration and daily limit status. NO SCANNING.
    sync_service = SyncService()
    remaining_today = sync_service.get_remaining_today(settings.daily_limit)

    return {
        "configured": True,
        "daily_limit": settings.daily_limit,
        "synced_today": sync_service._state.get("synced_today", 0),
        "remaining_today": remaining_today,
        "total_missing": 0,
        "unsynced_missing": 0,
        "missing_movies": [],
        "hide_future": settings.hide_future_releases,
        "root_folder": settings.root_folder_path,
        "last_sync_date": sync_service._state.get("last_sync_date"),
        "first_run": False
    }

@router.post("/scan")
async def perform_scan(data: SyncTriggerInput, request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Performs the actual scan (heavy). Called by 'Sync Now' and 'Dry Run' buttons."""
    # Check if configured
    if not settings.is_fully_configured:
        raise HTTPException(status_code=400, detail="Radarr or TMDB not configured")
    
    # ... KEEP ALL THE EXISTING CODE FROM THE OLD /trigger ENDPOINT ...
    # (The dry run logic, the background task for real sync, everything stays the same)
    # Check if configured
    if not settings.is_fully_configured:
        raise HTTPException(status_code=400, detail="Radarr or TMDB not configured")
    
    if data.dry_run:
        # Just return what would be added without actually adding
        sync_service = SyncService()
        radarr_client = RadarrClient(settings.radarr_url, settings.radarr_api_key)
        tmdb_service = TMDBService(settings.tmdb_api_key)
        
        radarr_movies = await radarr_client.get_movies()
        owned_tmdb_ids = {m.get("tmdbId") for m in radarr_movies if m.get("tmdbId")}
        
        missing_movies = await tmdb_service.find_collection_gaps(
            owned_tmdb_ids=owned_tmdb_ids,
            hide_future=settings.hide_future_releases,
            ignore_collections=sync_service.get_ignored_collections(),
            ignore_movies=sync_service.get_ignored_movies()
        )
        
        unsynced_missing = [
            m for m in missing_movies
            if not sync_service.is_synced(m["tmdb_id"])
        ]
        
        remaining = sync_service.get_remaining_today(settings.daily_limit)
        to_add = unsynced_missing[:remaining]
        
        return {
            "dry_run": True,
            "would_add": len(to_add),
            "movies": to_add,
            "remaining_today": remaining
        }
    else:
        # Run actual sync in background
        def run_sync():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            sync_service = SyncService()
            radarr_client = RadarrClient(settings.radarr_url, settings.radarr_api_key)
            tmdb_service = TMDBService(settings.tmdb_api_key)
            
            loop.run_until_complete(
                sync_service.sync_missing_movies(
                    radarr_client=radarr_client,
                    tmdb_service=tmdb_service,
                    root_folder_path=settings.root_folder_path,
                    daily_limit=settings.daily_limit,
                    hide_future=settings.hide_future_releases
                )
            )
        
        background_tasks.add_task(run_sync)
        
        return {
            "success": True,
            "message": "Sync started in background",
            "dry_run": False
        }


@router.post("/settings")
async def save_sync_settings(data: SyncSettingsInput, request: Request) -> Dict[str, Any]:
    """Save sync settings (daily limit, sync time, hide future)."""
    settings.set_sync_config(data.daily_limit, data.sync_time, data.hide_future)
    
    # Update app state
    request.app.state.daily_limit = data.daily_limit
    request.app.state.hide_future_releases = data.hide_future
    
    return {"success": True, "message": "Sync settings saved"}


@router.get("/settings")
async def get_sync_settings(request: Request) -> Dict[str, Any]:
    """Get current sync settings."""
    return {
        "daily_limit": settings.daily_limit,
        "sync_time": settings.sync_time,
        "hide_future": settings.hide_future_releases
    }

@router.get("/progress")
async def get_scan_progress(request: Request) -> Dict[str, Any]:
    """Get current scan progress."""
    # This would need to track progress from the scanner
    # For now, return a simple response
    return {
        "status": "idle",
        "current": 0,
        "total": 0,
        "current_movie": "",
        "is_running": False
    }

@router.post("/ignore/collection")
async def add_ignored_collection(data: IgnoreCollectionInput, request: Request) -> Dict[str, Any]:
    """Add a collection to the ignore list."""
    sync_service = SyncService()
    sync_service.add_ignored_collection(data.collection_id)
    return {"success": True, "message": f"Collection {data.collection_id} ignored"}


@router.delete("/ignore/collection/{collection_id}")
async def remove_ignored_collection(collection_id: int, request: Request) -> Dict[str, Any]:
    """Remove a collection from the ignore list."""
    sync_service = SyncService()
    sync_service.remove_ignored_collection(collection_id)
    return {"success": True, "message": f"Collection {collection_id} unignored"}


@router.post("/ignore/movie")
async def add_ignored_movie(data: IgnoreMovieInput, request: Request) -> Dict[str, Any]:
    """Add a movie to the ignore list."""
    sync_service = SyncService()
    sync_service.add_ignored_movie(data.tmdb_id)
    return {"success": True, "message": f"Movie {data.tmdb_id} ignored"}


@router.delete("/ignore/movie/{tmdb_id}")
async def remove_ignored_movie(tmdb_id: int, request: Request) -> Dict[str, Any]:
    """Remove a movie from the ignore list."""
    sync_service = SyncService()
    sync_service.remove_ignored_movie(tmdb_id)
    return {"success": True, "message": f"Movie {tmdb_id} unignored"}


@router.get("/ignore")
async def get_ignored(request: Request) -> Dict[str, Any]:
    """Get list of ignored collections and movies."""
    sync_service = SyncService()
    return {
        "ignored_collections": sync_service.get_ignored_collections(),
        "ignored_movies": sync_service.get_ignored_movies()
    }