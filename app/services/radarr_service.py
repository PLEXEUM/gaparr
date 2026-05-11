"""Radarr API client - adapted from resizarr project."""

import httpx
from typing import Optional, List, Dict, Any, Set, Tuple
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

    async def _get_default_quality_profile_id(self) -> Optional[int]:
        """Fetch the first available quality profile ID from Radarr."""
        try:
            profiles = await self._request("GET", "qualityprofile")
            if profiles and len(profiles) > 0:
                profile_id = profiles[0].get("id")
                profile_name = profiles[0].get("name")
                logger.info(f"Using quality profile: {profile_name} (ID: {profile_id})")
                return profile_id
            else:
                logger.error("No quality profiles found in Radarr")
                return None
        except Exception as e:
            logger.error(f"Failed to fetch quality profiles: {e}")
            return None

    async def get_movies(self, page_size: int = 100) -> List[Dict[str, Any]]:
        """Fetch all movies from Radarr (paginated)."""
        all_movies = []
        page = 1

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

    async def get_movies_batch(self, batch_size: int = 100) -> List[List[Dict[str, Any]]]:
        """Fetch movies and return them in batches for memory efficiency."""
        all_movies = await self.get_movies()
        
        # Return in batches
        for i in range(0, len(all_movies), batch_size):
            yield all_movies[i:i + batch_size]

    async def get_root_folders(self) -> List[Dict[str, Any]]:
        """Fetch available root folders from Radarr."""
        return await self._request("GET", "rootfolder")

    async def get_movies_with_collections(self) -> List[Dict[str, Any]]:
        """Fetch movies and check if Radarr provides collectionTmdbId."""
        movies = await self.get_movies()
    
        # Log sample to see what data Radarr returns
        if movies:
            sample = movies[0]
            logger.info(f"Sample movie keys: {sample.keys()}")
            if 'collectionTmdbId' in sample:
                logger.info("Radarr provides collectionTmdbId natively!")
            else:
                logger.info("Radarr does not provide collectionTmdbId, using TMDB API")
        return movies

    async def get_owned_tmdb_ids(self) -> Tuple[Set[int], Dict[int, Dict]]:
        """
        Get set of owned TMDB IDs and movie metadata.
        Returns: (set of tmdb_ids, dict of tmdb_id -> movie_info)
        """
        movies = await self.get_movies()
        owned_ids = set()
        movie_info = {}
        
        for movie in movies:
            tmdb_id = movie.get("tmdbId")
            if tmdb_id:
                owned_ids.add(tmdb_id)
                movie_info[tmdb_id] = {
                    "radarr_id": movie.get("id"),
                    "title": movie.get("title"),
                    "year": movie.get("year"),
                    "has_file": movie.get("hasFile", False),
                    "monitored": movie.get("monitored", False),
                    "collection_id": movie.get("collectionTmdbId")  # May be None (Radarr v4+)
                }
        
        logger.info(f"Found {len(owned_ids)} unique TMDB IDs in Radarr")
        return owned_ids, movie_info

    async def get_movies_by_collection(self, collection_tmdb_id: int) -> List[Dict]:
        """Get all movies belonging to a specific collection from Radarr."""
        movies = await self.get_movies()
        
        # Filter movies that belong to the collection
        collection_movies = []
        for movie in movies:
            movie_collection_id = movie.get("collectionTmdbId")
            if movie_collection_id and movie_collection_id == collection_tmdb_id:
                collection_movies.append(movie)
        
        logger.info(f"Found {len(collection_movies)} movies in collection {collection_tmdb_id}")
        return collection_movies

    async def add_movie(
        self, 
        tmdb_id: int, 
        title: str, 
        root_folder_path: str, 
        quality_profile_id: Optional[int] = None,
        monitor: str = "movieOnly",
        search_now: bool = False
    ) -> Dict[str, Any]:
        """
        Add a movie to Radarr using TMDB ID.
    
        Args:
            tmdb_id: TMDB movie ID
            title: Movie title
            root_folder_path: Root folder path in Radarr
            quality_profile_id: Quality profile ID (optional, auto-fetches if not specified)
            monitor: Monitoring setting ("movieOnly", "all", "none")
            search_now: Whether to trigger search after adding
        """
        # Auto-fetch quality profile if not provided
        final_quality_profile_id = quality_profile_id
        if not final_quality_profile_id:
            final_quality_profile_id = await self._get_default_quality_profile_id()
            if not final_quality_profile_id:
                raise Exception("No quality profile found in Radarr. Please configure at least one quality profile.")
    
        # Build complete payload with ALL required fields
        payload = {
            "tmdbId": tmdb_id,
            "title": title,
            "qualityProfileId": final_quality_profile_id,
            "rootFolderPath": root_folder_path,
            "minimumAvailability": "released",  # REQUIRED field
            "monitored": True,                   # Top-level monitored flag
            "addOptions": {
                "monitor": monitor,
                "searchForMovie": search_now
            }
        }

        logger.info(f"Adding movie to Radarr: {title} (TMDB: {tmdb_id})")
        logger.debug(f"Payload: {payload}")

        try:
            result = await self._request("POST", "movie", json=payload)
            logger.info(f"Successfully added {title} to Radarr")
            return result
        except Exception as e:
            logger.error(f"Failed to add {title}: {e}")
            raise

    async def add_movies_batch(
        self,
        movies: List[Dict],
        root_folder_path: str,
        quality_profile_id: Optional[int] = None,
        delay_between: float = 0.5
    ) -> Dict[str, Any]:
        """
        Add multiple movies to Radarr with a delay between requests.
        
        Args:
            movies: List of dicts with 'tmdb_id' and 'title' keys
            root_folder_path: Root folder path in Radarr
            quality_profile_id: Quality profile ID (optional)
            delay_between: Seconds to wait between requests
        """
        results = {
            "added": [],
            "failed": [],
            "total": len(movies)
        }
        
        for idx, movie in enumerate(movies):
            try:
                result = await self.add_movie(
                    tmdb_id=movie["tmdb_id"],
                    title=movie["title"],
                    root_folder_path=root_folder_path,
                    quality_profile_id=quality_profile_id
                )
                results["added"].append({
                    "tmdb_id": movie["tmdb_id"],
                    "title": movie["title"],
                    "radarr_id": result.get("id")
                })
                logger.info(f"Added movie {idx + 1}/{len(movies)}: {movie['title']}")
                
                # Delay between requests to avoid overwhelming Radarr
                if idx < len(movies) - 1 and delay_between > 0:
                    await asyncio.sleep(delay_between)
                    
            except Exception as e:
                logger.error(f"Failed to add {movie['title']}: {e}")
                results["failed"].append({
                    "tmdb_id": movie["tmdb_id"],
                    "title": movie["title"],
                    "error": str(e)
                })
        
        return results

    async def trigger_search(self, movie_id: int) -> Dict[str, Any]:
        """Trigger a search for a specific movie."""
        logger.info(f"Triggering search for movie ID: {movie_id}")
        return await self._request("POST", "command", json={
            "name": "MoviesSearch",
            "movieIds": [movie_id]
        })

    async def trigger_search_batch(self, movie_ids: List[int], delay_between: float = 1.0) -> Dict[str, Any]:
        """Trigger searches for multiple movies."""
        results = {
            "triggered": [],
            "failed": [],
            "total": len(movie_ids)
        }
        
        for idx, movie_id in enumerate(movie_ids):
            try:
                await self.trigger_search(movie_id)
                results["triggered"].append(movie_id)
                
                if idx < len(movie_ids) - 1 and delay_between > 0:
                    await asyncio.sleep(delay_between)
            except Exception as e:
                logger.error(f"Failed to trigger search for movie {movie_id}: {e}")
                results["failed"].append({"movie_id": movie_id, "error": str(e)})
        
        return results

    async def get_quality_profiles(self) -> List[Dict[str, Any]]:
        """Fetch available quality profiles from Radarr."""
        try:
            return await self._request("GET", "qualityprofile")
        except Exception as e:
            logger.warning(f"Failed to fetch quality profiles: {e}")
            return []

    async def get_radarr_version(self) -> Optional[str]:
        """Get Radarr version to determine feature support."""
        try:
            status = await self._request("GET", "system/status")
            return status.get("version")
        except Exception as e:
            logger.warning(f"Failed to get Radarr version: {e}")
            return None

    async def supports_native_collections(self) -> bool:
        """Check if Radarr version supports native collectionTmdbId."""
        version = await self.get_radarr_version()
        if not version:
            return False
        
        # Radarr v4+ supports collectionTmdbId
        parts = version.split('.')
        if len(parts) >= 1:
            major = int(parts[0])
            return major >= 4
        
        return False