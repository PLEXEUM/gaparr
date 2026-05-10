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
    level=getattr(logging, settings._settings.get("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("gaparr")


# Setup data directory
Path(settings.data_dir).mkdir(exist_ok=True)


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
            
            result = await sync_service.sync_missing_movies(
                radarr_client=radarr_client,
                tmdb_service=tmdb_service,
                root_folder_path=settings.root_folder_path,
                daily_limit=settings.daily_limit,
                hide_future=settings.hide_future_releases
            )
            
            logger.info(f"Scheduled sync complete: added {result['added_count']} movies")
        
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
    else:
        logger.info("Scheduler not started - Radarr or TMDB not configured")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Gaparr...")
    logger.info(f"Data directory: {settings.data_dir}")
    
    # Start scheduler
    scheduler.start()
    update_scheduler()
    
    # Store settings in app state for API access
    app.state.radarr_url = settings.radarr_url
    app.state.radarr_api_key = settings.radarr_api_key
    app.state.radarr_configured = settings.radarr_configured
    app.state.tmdb_api_key = settings.tmdb_api_key
    app.state.tmdb_configured = settings.tmdb_configured
    app.state.daily_limit = settings.daily_limit
    app.state.hide_future_releases = settings.hide_future_releases
    app.state.root_folder_path = settings.root_folder_path
    
    logger.info(f"Gaparr started on port {settings._settings.get('PORT', 7117)}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Gaparr...")
    scheduler.shutdown()


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
    return {"status": "ok"}

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
    port = settings._settings.get("PORT", 7117)
    host = settings._settings.get("HOST", "0.0.0.0")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False
    )