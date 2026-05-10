"""Gaparr - Automatically add missing collection movies to Radarr."""

from contextlib import asynccontextmanager
from pathlib import Path
import logging
import asyncio

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.settings import settings
from app.services.radarr_service import RadarrClient
from app.services.tmdb_service import TMDBService
from app.services.sync_service import SyncService
from app.api import logs

# Import API routers
from app.api import radarr, tmdb, sync

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("gaparr")


# Setup data directory
Path(settings.data_dir).mkdir(exist_ok=True)


async def prewarm_cache():
    """Pre-warm TMDB cache with popular collections on startup."""
    if not settings.prewarm_cache_on_startup:
        logger.info("Cache pre-warming disabled in settings")
        return
    
    if not settings.tmdb_configured:
        logger.info("Cache pre-warming skipped: TMDB not configured")
        return
    
    try:
        logger.info("Starting cache pre-warming with popular movies...")
        tmdb_service = TMDBService(settings.tmdb_api_key, settings.data_dir)
        
        # Popular TMDB movie IDs to warm the cache (various genres/eras)
        # These are well-known movies that are likely to be in many collections
        popular_movie_ids = [
            550,    # Fight Club
            238,    # The Godfather
            497,    # The Green Mile
            680,    # Pulp Fiction
            27205,  # Inception
            157336, # Interstellar
            11,     # Star Wars
            1891,   # The Empire Strikes Back
            155,    # The Dark Knight
            120,    # The Lord of the Rings: The Fellowship of the Ring
            122,    # The Lord of the Rings: The Return of the King
            13,     # Forrest Gump
            274,    # The Silence of the Lambs
            597,    # Titanic
            424,    # Schindler's List
        ]
        
        # Fetch movie details (this will populate cache)
        await tmdb_service.get_movie_details_batch(popular_movie_ids)
        
        # Also fetch collections for any movies that belong to collections
        collections_found = set()
        for movie_id in popular_movie_ids:
            collection_id = await tmdb_service.get_movie_collection_id(movie_id)
            if collection_id:
                collections_found.add(collection_id)
        
        # Fetch the collections
        for collection_id in list(collections_found)[:10]:  # Limit to 10 collections
            await tmdb_service.get_collection(collection_id)
        
        cache_stats = tmdb_service.get_cache_stats()
        logger.info(f"Cache pre-warming complete: {cache_stats.get('movies_cached', 0)} movies, "
                   f"{cache_stats.get('collections_cached', 0)} collections cached")
        
    except Exception as e:
        logger.warning(f"Cache pre-warming failed (non-critical): {e}")


def run_scheduled_sync():
    """Background task to run sync on schedule."""
    if not settings.is_fully_configured:
        logger.warning("Scheduled sync skipped: Radarr or TMDB not fully configured")
        return
    
    try:
        async def _sync():
            radarr_client = RadarrClient(settings.radarr_url, settings.radarr_api_key)
            tmdb_service = TMDBService(settings.tmdb_api_key, settings.data_dir)
            sync_service = SyncService(settings.data_dir)
            
            # Apply cache and rate limiting settings to TMDB service
            if not settings.enable_cache:
                logger.info("Cache is disabled for scheduled sync")
            
            # Configure rate limiter based on settings
            if settings.enable_rate_limiting:
                tmdb_service.rate_limiter.max_calls = settings.api_rate_limit
                logger.info(f"Rate limiting enabled: {settings.api_rate_limit} calls/second")
            else:
                tmdb_service.rate_limiter.max_calls = 999999  # Effectively unlimited
                logger.info("Rate limiting disabled for scheduled sync")
            
            result = await sync_service.sync_missing_movies(
                radarr_client=radarr_client,
                tmdb_service=tmdb_service,
                root_folder_path=settings.root_folder_path,
                daily_limit=settings.daily_limit,
                hide_future=settings.hide_future_releases
            )
            
            logger.info(f"Scheduled sync complete: added {result['added_count']} movies, "
                       f"failed {result['failed_count']}, "
                       f"cache hit rate: {result.get('cache_stats', {}).get('cache_hit_rate_percent', 0)}%")
        
        asyncio.run(_sync())
    except Exception as e:
        logger.error(f"Scheduled sync failed: {e}")


# Initialize scheduler
scheduler = BackgroundScheduler()


def update_scheduler():
    """Update scheduler with current sync time from settings."""
    # Remove existing job if present
    if scheduler.get_job("daily_sync"):
        scheduler.remove_job("daily_sync")
    
    # Only add job if Radarr and TMDB are configured
    if settings.is_fully_configured:
        sync_time_parts = settings.sync_time.split(":")
        hour = int(sync_time_parts[0])
        minute = int(sync_time_parts[1]) if len(sync_time_parts) > 1 else 0
        
        scheduler.add_job(
            run_scheduled_sync,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_sync",
            replace_existing=True
        )
        logger.info(f"Scheduled daily sync at {hour:02d}:{minute:02d}")
        
        # Log cache configuration for scheduled tasks
        logger.info(f"Cache TTL: {settings.cache_ttl_days} days")
        logger.info(f"Batch size: {settings.batch_size} movies per batch")
        logger.info(f"Max concurrent API calls: {settings.max_concurrent_api_calls}")
    else:
        logger.info("Scheduler not started - Radarr or TMDB not configured")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Gaparr...")
    logger.info(f"Data directory: {settings.data_dir}")
    logger.info(f"Cache enabled: {settings.enable_cache}")
    logger.info(f"Rate limiting enabled: {settings.enable_rate_limiting}")
    
    # Start scheduler
    scheduler.start()
    update_scheduler()
    
    # Pre-warm cache if enabled (non-blocking)
    if settings.prewarm_cache_on_startup:
        asyncio.create_task(prewarm_cache())
    
    # Store settings in app state for API access
    app.state.radarr_url = settings.radarr_url
    app.state.radarr_api_key = settings.radarr_api_key
    app.state.radarr_configured = settings.radarr_configured
    app.state.tmdb_api_key = settings.tmdb_api_key
    app.state.tmdb_configured = settings.tmdb_configured
    app.state.daily_limit = settings.daily_limit
    app.state.hide_future_releases = settings.hide_future_releases
    app.state.root_folder_path = settings.root_folder_path
    
    # Cache settings in app state
    app.state.enable_cache = settings.enable_cache
    app.state.cache_ttl_days = settings.cache_ttl_days
    app.state.batch_size = settings.batch_size
    app.state.max_concurrent_api_calls = settings.max_concurrent_api_calls
    app.state.enable_rate_limiting = settings.enable_rate_limiting
    app.state.api_rate_limit = settings.api_rate_limit
    
    logger.info(f"Gaparr started on port {settings.port}")
    logger.info(f"Web UI available at http://{settings.host}:{settings.port}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Gaparr...")
    
    # Shutdown scheduler
    scheduler.shutdown()
    
    # Log final cache stats if TMDB was configured
    if settings.tmdb_configured:
        try:
            tmdb_service = TMDBService(settings.tmdb_api_key, settings.data_dir)
            stats = tmdb_service.get_cache_stats()
            logger.info(f"Final cache stats - Movies: {stats.get('movies_cached', 0)}, "
                       f"Collections: {stats.get('collections_cached', 0)}, "
                       f"Hit rate: {stats.get('cache_hit_rate_percent', 0)}%")
        except Exception as e:
            logger.warning(f"Failed to log final cache stats: {e}")


# Create FastAPI app
app = FastAPI(
    title="Gaparr",
    description="Automatically add missing collection movies to Radarr",
    version="1.0.0",
    lifespan=lifespan
)

# Health check endpoint
@app.get("/health")
async def health():
    """Health check endpoint for container orchestration."""
    return {
        "status": "ok",
        "configured": settings.is_fully_configured,
        "cache_enabled": settings.enable_cache,
        "version": "1.0.0"
    }


# Detailed health endpoint for debugging
@app.get("/health/detailed")
async def health_detailed():
    """Detailed health check with cache statistics."""
    health_data = {
        "status": "ok",
        "configured": settings.is_fully_configured,
        "cache_enabled": settings.enable_cache,
        "radarr_configured": settings.radarr_configured,
        "tmdb_configured": settings.tmdb_configured,
        "scheduler_running": scheduler.running,
        "daily_limit": settings.daily_limit,
        "sync_time": settings.sync_time,
        "cache_ttl_days": settings.cache_ttl_days,
        "batch_size": settings.batch_size
    }
    
    # Add cache stats if TMDB configured
    if settings.tmdb_configured:
        try:
            tmdb_service = TMDBService(settings.tmdb_api_key, settings.data_dir)
            health_data["cache_stats"] = tmdb_service.get_cache_stats()
        except Exception as e:
            health_data["cache_error"] = str(e)
    
    return health_data


# Mount static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


# Include API routers
app.include_router(radarr.router)
app.include_router(tmdb.router)
app.include_router(sync.router)
app.include_router(logs.router)


# Frontend routes
@app.get("/")
async def index(request: Request):
    """Dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/settings")
async def settings_page(request: Request):
    """Settings page."""
    return templates.TemplateResponse("settings.html", {"request": request})


@app.get("/logs")
async def logs_page(request: Request):
    """Logs page."""
    return templates.TemplateResponse("logs.html", {"request": request})


if __name__ == "__main__":
    import uvicorn
    port = settings.port
    host = settings.host
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level=settings.log_level.lower()
    )