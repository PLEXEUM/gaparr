"""Logs API endpoints for real log file access."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])

# Docker container log location - adjust if different
LOG_FILE = Path("/app/logs/gaparr.log")


@router.get("")
async def get_logs(lines: int = 200) -> Dict[str, Any]:
    """Return the last N lines of the log file."""
    if not LOG_FILE.exists():
        # Try alternative location
        alt_log = Path("/var/log/gaparr.log")
        if alt_log.exists():
            LOG_FILE = alt_log
        else:
            return {"lines": [], "message": "Log file not found", "total_lines": 0, "showing": 0}
    
    try:
        with open(LOG_FILE, "r") as f:
            all_lines = f.readlines()
        
        last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        
        return {
            "lines": [line.strip() for line in last_lines],
            "total_lines": len(all_lines),
            "showing": len(last_lines),
            "log_file": LOG_FILE.name
        }
    except Exception as e:
        logger.error(f"Failed to read logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("")
async def clear_logs() -> Dict[str, Any]:
    """Clear the log file."""
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "w") as f:
                f.write("")
            logger.info("Logs cleared by user")
            return {"success": True, "message": "Logs cleared"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    return {"success": True, "message": "No log file to clear"}


@router.get("/download")
async def download_logs():
    """Download the log file."""
    if not LOG_FILE.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    
    return FileResponse(
        path=LOG_FILE,
        media_type="text/plain",
        filename=f"gaparr_logs_{Path(LOG_FILE).stat().st_mtime}.log"
    )