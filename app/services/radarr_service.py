"""Radarr API client - adapted from resizarr project."""

import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)


class RadarrClient:
    """Radarr API client for adding movies and fetching library."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, endpoint: str, timeout: int = 30, **kwargs) -> Dict[str, Any]:
        """Make an HTTP request to Radarr API with retry logic."""
        url = f"{self.base_url}/api/v3/{endpoint}"
        last_error = None

        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(method, url, headers=self.headers, **kwargs)
                    response.raise_for_status()
                    if response.status_code == 204:
                        return {}
                    return response.json()
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"Radarr API error (attempt {attempt}/3): {e.response.status_code}")
            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"Radarr connection error (attempt {attempt}/3): {e}")

            if attempt < 3:
                await asyncio.sleep(2 ** attempt)

        raise ConnectionError(f"Radarr API unreachable after 3 attempts: {last_error}")

    async def test_connection(self) -> tuple[bool, str]:
        """Test connection to Radarr."""
        try:
            await self._request("GET", "system/status")
            return True, "Connected to Radarr successfully"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    async def get_movies(self) -> List[Dict[str, Any]]:
        """Fetch all movies from Radarr (paginated)."""
        all_movies = []
        page = 1
        page_size = 50

        while True:
            data = await self._request(
                "GET", "movie",
                params={"page": page, "pageSize": page_size}
            )

            if isinstance(data, list):
                all_movies.extend(data)
                break

            records = data.get("records", [])
            all_movies.extend(records)

            total = data.get("totalRecords", 0)
            if len(all_movies) >= total or not records:
                break

            page += 1

        logger.info(f"Fetched {len(all_movies)} movies from Radarr")
        return all_movies

    async def get_root_folders(self) -> List[Dict[str, Any]]:
        """Fetch available root folders from Radarr."""
        return await self._request("GET", "rootfolder")

    async def add_movie(self, tmdb_id: int, title: str, root_folder_path: str, quality_profile_id: Optional[int] = None) -> Dict[str, Any]:
        """Add a movie to Radarr using TMDB ID."""
        payload = {
            "tmdbId": tmdb_id,
            "title": title,
            "rootFolderPath": root_folder_path,
            "addOptions": {
                "monitor": "movieOnly",
                "searchForMovie": False  # Don't auto-search, let user decide or schedule
            }
        }

        # Only add quality profile if specified (otherwise Radarr uses default)
        if quality_profile_id:
            payload["qualityProfileId"] = quality_profile_id

        logger.info(f"Adding movie to Radarr: {title} (TMDB: {tmdb_id})")
        return await self._request("POST", "movie", json=payload)

    async def trigger_search(self, movie_id: int) -> Dict[str, Any]:
        """Trigger a search for a specific movie."""
        logger.info(f"Triggering search for movie ID: {movie_id}")
        return await self._request("POST", "command", json={
            "name": "MoviesSearch",
            "movieIds": [movie_id]
        })