"""Logs API endpoints for real log file access."""

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])

# Try multiple possible log locations
LOG_PATHS = [
    Path("/app/logs/gaparr.log"),
    Path("/var/log/gaparr.log"),
    Path("logs/gaparr.log"),
    Path("/app/data/gaparr.log"),
]


def find_log_file() -> Path | None:
    """Find the first existing log file."""
    for path in LOG_PATHS:
        if path.exists():
            return path
    return None


@router.get("")
async def get_logs(lines: int = 200) -> Dict[str, Any]:
    """Return the last N lines of the log file."""
    log_file = find_log_file()
    
    if not log_file:
        # Return empty result instead of error
        return {
            "lines": [],
            "message": "No log file found. Logs will appear here when Gaparr writes to a file.",
            "total_lines": 0,
            "showing": 0
        }
    
    try:
        with open(log_file, "r") as f:
            all_lines = f.readlines()
        
        last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        
        return {
            "lines": [line.strip() for line in last_lines],
            "total_lines": len(all_lines),
            "showing": len(last_lines),
            "log_file": log_file.name
        }
    except Exception as e:
        logger.error(f"Failed to read logs: {e}")
        return {
            "lines": [],
            "error": str(e),
            "total_lines": 0,
            "showing": 0
        }


@router.delete("")
async def clear_logs() -> Dict[str, Any]:
    """Clear the log file."""
    log_file = find_log_file()
    
    if log_file and log_file.exists():
        try:
            with open(log_file, "w") as f:
                f.write("")
            logger.info("Logs cleared by user")
            return {"success": True, "message": "Logs cleared"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    return {"success": True, "message": "No log file to clear"}


@router.get("/download")
async def download_logs():
    """Download the log file."""
    log_file = find_log_file()
    
    if not log_file or not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    
    return FileResponse(
        path=log_file,
        media_type="text/plain",
        filename=f"gaparr_logs.log"
    )