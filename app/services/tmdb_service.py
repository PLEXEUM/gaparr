"""TMDB API service for collection and movie data."""

import httpx
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import date
import logging

logger = logging.getLogger(__name__)


class TMDBService:
    """The Movie Database API client for collection discovery."""

    def __init__(self, api_key: str, data_dir: str = "data"):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/w500"
        self.data_dir = Path(data_dir)
        self.cache_file = self.data_dir / "tmdb_cache.json"
        
        # In-memory caches
        self._collection_cache: Dict[int, Dict[str, Any]] = {}
        self._movie_collection_cache: Dict[int, Optional[int]] = {}
        
        # Load cached data from disk
        self._load_cache()

    def _load_cache(self) -> None:
        """Load cached TMDB data from JSON file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as f:
                    cache = json.load(f)
                    # Convert string keys back to integers
                    self._movie_collection_cache = {
                        int(k): v for k, v in cache.get("movie_collection_cache", {}).items()
                    }
                    self._collection_cache = {
                        int(k): v for k, v in cache.get("collection_cache", {}).items()
                    }
                    logger.info(f"Loaded TMDB cache: {len(self._movie_collection_cache)} movies, {len(self._collection_cache)} collections")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load TMDB cache: {e}")

    def _save_cache(self) -> None:
        """Save cached TMDB data to JSON file."""
        try:
            cache_data = {
                "movie_collection_cache": self._movie_collection_cache,
                "collection_cache": self._collection_cache
            }
            with open(self.cache_file, "w") as f:
                json.dump(cache_data, f, indent=2)
            logger.debug(f"Saved TMDB cache: {len(self._movie_collection_cache)} movies, {len(self._collection_cache)} collections")
        except IOError as e:
            logger.warning(f"Failed to save TMDB cache: {e}")

    async def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a request to TMDB API."""
        url = f"{self.base_url}/{endpoint}"
        default_params = {
            "api_key": self.api_key,
            "language": "en-US"
        }
        if params:
            default_params.update(params)

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, params=default_params)
            response.raise_for_status()
            return response.json()

    async def test_connection(self) -> tuple[bool, str]:
        """Test if TMDB API key is valid."""
        try:
            await self._request("configuration")
            return True, "TMDB API key is valid"
        except Exception as e:
            return False, f"TMDB connection failed: {str(e)}"

    async def get_movie_collection_id(self, tmdb_id: int) -> Optional[int]:
        """Get the collection ID a movie belongs to."""
        if tmdb_id in self._movie_collection_cache:
            return self._movie_collection_cache[tmdb_id]

        try:
            data = await self._request(f"movie/{tmdb_id}")
            collection = data.get("belongs_to_collection")
            collection_id = collection["id"] if collection else None
            self._movie_collection_cache[tmdb_id] = collection_id
            self._save_cache()  # Save after each new lookup
            return collection_id
        except Exception as e:
            logger.warning(f"Failed to get collection for movie {tmdb_id}: {e}")
            self._movie_collection_cache[tmdb_id] = None
            self._save_cache()
            return None

    async def get_collection(self, collection_id: int) -> Optional[Dict[str, Any]]:
        """Get full collection details including all parts."""
        if collection_id in self._collection_cache:
            return self._collection_cache[collection_id]

        try:
            data = await self._request(f"collection/{collection_id}")
            self._collection_cache[collection_id] = data
            self._save_cache()  # Save after each new lookup
            return data
        except Exception as e:
            logger.warning(f"Failed to get collection {collection_id}: {e}")
            return None

    async def find_collection_gaps(
        self,
        owned_tmdb_ids: Set[int],
        hide_future: bool = True,
        ignore_collections: Optional[List[int]] = None,
        ignore_movies: Optional[List[int]] = None
    ) -> List[Dict[str, Any]]:
        """
        Find missing movies from collections based on owned movies.

        Returns:
            List of missing movies with details: tmdb_id, title, year, release_date,
            collection_name, collection_id, poster_url
        """
        if ignore_collections is None:
            ignore_collections = []
        if ignore_movies is None:
            ignore_movies = []

        seen_collections: Set[int] = set()
        missing_movies: Dict[int, Dict] = {}

        logger.info(f"Finding collection gaps for {len(owned_tmdb_ids)} owned movies")

        for tmdb_id in owned_tmdb_ids:
            collection_id = await self.get_movie_collection_id(tmdb_id)
            if not collection_id or collection_id in seen_collections:
                continue

            if collection_id in ignore_collections:
                logger.debug(f"Skipping ignored collection ID: {collection_id}")
                continue

            seen_collections.add(collection_id)

            collection = await self.get_collection(collection_id)
            if not collection:
                continue

            collection_name = collection.get("name", "Unknown Collection")
            parts = collection.get("parts", [])

            for part in parts:
                part_id = part.get("id")
                if not part_id:
                    continue

                if part_id in owned_tmdb_ids:
                    continue

                if part_id in ignore_movies:
                    continue

                if hide_future:
                    release_date_str = part.get("release_date", "")
                    if release_date_str:
                        try:
                            release_date = date.fromisoformat(release_date_str[:10])
                            if release_date > date.today():
                                logger.debug(f"Skipping future release: {part.get('title')} ({release_date})")
                                continue
                        except ValueError:
                            pass

                if part_id not in missing_movies:
                    poster = part.get("poster_path")
                    missing_movies[part_id] = {
                        "tmdb_id": part_id,
                        "title": part.get("title", "Unknown"),
                        "year": part.get("release_date", "")[:4] if part.get("release_date") else "N/A",
                        "release_date": part.get("release_date", ""),
                        "collection_name": collection_name,
                        "collection_id": collection_id,
                        "poster_url": f"{self.image_base_url}{poster}" if poster else None,
                        "overview": part.get("overview", "")
                    }

        result = list(missing_movies.values())
        result.sort(key=lambda x: (x["collection_name"], x["year"]))
        logger.info(f"Found {len(result)} missing movies from {len(seen_collections)} collections")
        return result