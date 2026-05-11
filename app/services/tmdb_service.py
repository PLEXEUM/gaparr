"""TMDB API service for collection and movie data."""

import asyncio
import httpx
import json
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Set, Tuple
from contextlib import asynccontextmanager
from app.settings import settings
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple rate limiter for TMDB API (50 requests per second default)."""
    
    def __init__(self, max_calls: int = 50, period: float = 1.0):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()
    
    async def acquire(self):
        """Acquire permission to make an API call."""
        now = time.time()
        
        # Remove calls older than the period
        while self.calls and now - self.calls[0] > self.period:
            self.calls.popleft()
        
        # If we've hit the limit, wait
        if len(self.calls) >= self.max_calls:
            sleep_time = self.period - (now - self.calls[0])
            if sleep_time > 0:
                logger.debug(f"Rate limit reached, sleeping for {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
            return await self.acquire()
        
        self.calls.append(now)
        return True


class TMDBService:
    """The Movie Database API client for collection discovery."""

    def __init__(self, api_key: str, data_dir: str = "data"):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/w500"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        # Database for persistent caching
        self.db_path = self.data_dir / "tmdb_cache.db"
        self._init_database()
        
        # Rate limiter (50 requests per second - TMDB free tier limit)
        self.rate_limiter = RateLimiter(max_calls=50, period=1.0)
        
        # In-memory caches for current session (faster than DB)
        self._collection_cache: Dict[int, Dict[str, Any]] = {}
        self._movie_collection_cache: Dict[int, Optional[int]] = {}
        
        # Statistics tracking
        self._stats = {
            "api_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "rate_limit_waits": 0
        }
        
        # Load any existing cache from disk to memory
        self._load_memory_cache()
        
        logger.info(f"TMDB Service initialized with DB cache at {self.db_path}")

    def _init_database(self):
        """Initialize SQLite database for persistent caching."""
        with sqlite3.connect(self.db_path) as conn:
            # Movie cache table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS movie_cache (
                    tmdb_id INTEGER PRIMARY KEY,
                    collection_id INTEGER,
                    title TEXT,
                    release_date TEXT,
                    poster_path TEXT,
                    overview TEXT,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Collection cache table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collection_cache (
                    collection_id INTEGER PRIMARY KEY,
                    name TEXT,
                    data_json TEXT,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Indexes for performance
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_movie_collection 
                ON movie_cache(collection_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_movie_cached_at 
                ON movie_cache(cached_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_collection_cached_at 
                ON collection_cache(cached_at)
            """)
            
            # Statistics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_stats (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_cleanup TIMESTAMP,
                    total_api_calls INTEGER DEFAULT 0,
                    total_cache_hits INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO cache_stats (id, last_cleanup, total_api_calls, total_cache_hits)
                VALUES (1, CURRENT_TIMESTAMP, 0, 0)
            """)
            
            conn.commit()
            logger.debug("Database initialized successfully")

    def _load_memory_cache(self):
        """Load recent cache entries into memory for faster access."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Load recent movies (last 30 days)
                cursor = conn.execute("""
                    SELECT tmdb_id, collection_id FROM movie_cache 
                    WHERE cached_at > datetime('now', '-30 days')
                """)
                for row in cursor:
                    self._movie_collection_cache[row[0]] = row[1]
                
                # Load recent collections
                cursor = conn.execute("""
                    SELECT collection_id, data_json FROM collection_cache 
                    WHERE cached_at > datetime('now', '-30 days')
                """)
                for row in cursor:
                    self._collection_cache[row[0]] = json.loads(row[1])
                
                logger.debug(f"Loaded {len(self._movie_collection_cache)} movies and "
                           f"{len(self._collection_cache)} collections into memory cache")
        except Exception as e:
            logger.warning(f"Failed to load memory cache: {e}")

    def _save_movie_to_cache(self, tmdb_id: int, collection_id: Optional[int], 
                            title: str = None, release_date: str = None,
                            poster_path: str = None, overview: str = None):
        """Save movie data to cache."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO movie_cache 
                    (tmdb_id, collection_id, title, release_date, poster_path, overview, cached_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (tmdb_id, collection_id, title, release_date, poster_path, overview))
                conn.commit()
            # Update memory cache
            self._movie_collection_cache[tmdb_id] = collection_id
        except Exception as e:
            logger.warning(f"Failed to save movie to cache: {e}")

    def _save_collection_to_cache(self, collection_id: int, data: Dict[str, Any]):
        """Save collection data to cache."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO collection_cache 
                    (collection_id, name, data_json, cached_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (collection_id, data.get("name", "Unknown"), json.dumps(data)))
                conn.commit()
            # Update memory cache
            self._collection_cache[collection_id] = data
        except Exception as e:
            logger.warning(f"Failed to save collection to cache: {e}")

    def _get_cached_movie(self, tmdb_id: int, max_age_days: int = 30) -> Optional[Dict]:
        """Get movie from cache if not expired."""
        self._stats["cache_hits"] += 1
        
        # Check memory cache first
        if tmdb_id in self._movie_collection_cache:
            # Need to get full data from DB
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT collection_id, title, release_date, poster_path, overview 
                    FROM movie_cache 
                    WHERE tmdb_id = ? AND cached_at > datetime('now', ? || ' days')
                """, (tmdb_id, f'-{max_age_days}'))
                row = cursor.fetchone()
                if row:
                    return {
                        "collection_id": row[0],
                        "title": row[1],
                        "release_date": row[2],
                        "poster_path": row[3],
                        "overview": row[4]
                    }
        
        self._stats["cache_misses"] += 1
        self._stats["cache_hits"] -= 1  # Correct the increment
        return None

    def _get_cached_collection(self, collection_id: int, max_age_days: int = 30) -> Optional[Dict]:
        """Get collection from cache if not expired."""
        # Check memory cache first
        if collection_id in self._collection_cache:
            return self._collection_cache[collection_id]
        
        # Check database
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT data_json FROM collection_cache 
                WHERE collection_id = ? AND cached_at > datetime('now', ? || ' days')
            """, (collection_id, f'-{max_age_days}'))
            row = cursor.fetchone()
            if row:
                data = json.loads(row[0])
                self._collection_cache[collection_id] = data
                return data
        
        return None

    def clean_old_cache(self, max_age_days: int = 90):
        """Remove cache entries older than specified days."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Delete old movie cache
                movie_deleted = conn.execute("""
                    DELETE FROM movie_cache 
                    WHERE cached_at < datetime('now', ? || ' days')
                """, (f'-{max_age_days}',)).rowcount
                
                # Delete old collection cache
                collection_deleted = conn.execute("""
                    DELETE FROM collection_cache 
                    WHERE cached_at < datetime('now', ? || ' days')
                """, (f'-{max_age_days}',)).rowcount
                
                conn.execute("UPDATE cache_stats SET last_cleanup = CURRENT_TIMESTAMP WHERE id = 1")
                conn.commit()
                
                logger.info(f"Cleaned cache: removed {movie_deleted} movies and {collection_deleted} collections")
                return {"movies_deleted": movie_deleted, "collections_deleted": collection_deleted}
        except Exception as e:
            logger.error(f"Failed to clean cache: {e}")
            return {"error": str(e)}

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                movie_count = conn.execute("SELECT COUNT(*) FROM movie_cache").fetchone()[0]
                collection_count = conn.execute("SELECT COUNT(*) FROM collection_cache").fetchone()[0]
                stats = conn.execute("SELECT last_cleanup, total_api_calls, total_cache_hits FROM cache_stats WHERE id = 1").fetchone()
                
                total_api = stats[1] if stats else 0
                total_hits = stats[2] if stats else 0
                
                hit_rate = (total_hits / (total_api + total_hits) * 100) if (total_api + total_hits) > 0 else 0
                
                return {
                    "movies_cached": movie_count,
                    "collections_cached": collection_count,
                    "total_api_calls_all_time": total_api,
                    "total_cache_hits_all_time": total_hits,
                    "cache_hit_rate_percent": round(hit_rate, 2),
                    "session_api_calls": self._stats["api_calls"],
                    "session_cache_hits": self._stats["cache_hits"],
                    "session_cache_misses": self._stats["cache_misses"],
                    "last_cleanup": stats[0] if stats else None
                }
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {"error": str(e)}

    async def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a request to TMDB API with rate limiting and retries."""
        # Apply rate limiting
        await self.rate_limiter.acquire()
        
        url = f"{self.base_url}/{endpoint}"
        default_params = {
            "api_key": self.api_key,
            "language": "en-US"
        }
        if params:
            default_params.update(params)

        # Retry logic with exponential backoff
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(url, params=default_params)
                    response.raise_for_status()
                    
                    # Update stats
                    self._stats["api_calls"] += 1
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute("UPDATE cache_stats SET total_api_calls = total_api_calls + 1 WHERE id = 1")
                        conn.commit()
                    
                    return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Too Many Requests
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Rate limit hit, waiting {wait_time}s before retry")
                    await asyncio.sleep(wait_time)
                    continue
                raise
            except (httpx.RequestError, httpx.TimeoutException) as e:
                if attempt == max_retries - 1:
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s")
                await asyncio.sleep(wait_time)
        
        raise Exception(f"Failed to fetch {endpoint} after {max_retries} attempts")

    async def test_connection(self) -> tuple[bool, str]:
        """Test if TMDB API key is valid."""
        try:
            await self._request("configuration")
            return True, "TMDB API key is valid"
        except Exception as e:
            return False, f"TMDB connection failed: {str(e)}"

    async def get_movie_collection_id(self, tmdb_id: int, use_cache: bool = True) -> Optional[int]:
        """Get the collection ID a movie belongs to."""
        # Check cache first
        if use_cache:
            cached = self._get_cached_movie(tmdb_id)
            if cached:
                return cached.get("collection_id")

        # Fetch from API
        try:
            data = await self._request(f"movie/{tmdb_id}")
            collection = data.get("belongs_to_collection")
            collection_id = collection["id"] if collection else None
            
            # Save to cache
            self._save_movie_to_cache(
                tmdb_id=tmdb_id,
                collection_id=collection_id,
                title=data.get("title"),
                release_date=data.get("release_date"),
                poster_path=data.get("poster_path"),
                overview=data.get("overview")
            )
            
            return collection_id
        except Exception as e:
            logger.warning(f"Failed to get collection for movie {tmdb_id}: {e}")
            # Cache the failure to avoid repeated attempts
            self._save_movie_to_cache(tmdb_id, None)
            return None

    async def get_collection(self, collection_id: int, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """Get full collection details including all parts."""
        # Check cache first
        if use_cache:
            cached = self._get_cached_collection(collection_id)
            if cached:
                return cached

        # Fetch from API
        try:
            data = await self._request(f"collection/{collection_id}")
            self._save_collection_to_cache(collection_id, data)
            return data
        except Exception as e:
            logger.warning(f"Failed to get collection {collection_id}: {e}")
            return None

    async def get_movie_details_batch(self, tmdb_ids: List[int], use_cache: bool = True) -> Dict[int, Dict]:
        """Get details for multiple movies efficiently using caching."""
        results = {}
        missing_ids = []
        
        # Check cache first
        if use_cache:
            for tmdb_id in tmdb_ids:
                cached = self._get_cached_movie(tmdb_id)
                if cached:
                    results[tmdb_id] = cached
                else:
                    missing_ids.append(tmdb_id)
        else:
            missing_ids = tmdb_ids
        
        # Fetch missing ones (with rate limiting, they'll be spread out)
        for tmdb_id in missing_ids:
            try:
                data = await self._request(f"movie/{tmdb_id}")
                collection = data.get("belongs_to_collection")
                collection_id = collection["id"] if collection else None
                
                movie_data = {
                    "collection_id": collection_id,
                    "title": data.get("title"),
                    "release_date": data.get("release_date"),
                    "poster_path": data.get("poster_path"),
                    "overview": data.get("overview")
                }
                
                results[tmdb_id] = movie_data
                self._save_movie_to_cache(tmdb_id, collection_id, **movie_data)
            except Exception as e:
                logger.warning(f"Failed to get details for movie {tmdb_id}: {e}")
                results[tmdb_id] = {"error": str(e)}
        
        return results

    async def find_collection_gaps(
        self,
        owned_tmdb_ids: Set[int],
        hide_future: bool = True,
        ignore_collections: Optional[List[int]] = None,
        ignore_movies: Optional[List[int]] = None,
        batch_size: int = 20,
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Find missing movies from collections based on owned movies.
        OPTIMIZED: Uses caching, batch processing, and parallel fetching.
    
        Args:
            progress_callback: Async function called with (message, current, total)
        """
        if ignore_collections is None:
            ignore_collections = []
        if ignore_movies is None:
            ignore_movies = []

        logger.info(f"Finding collection gaps for {len(owned_tmdb_ids)} owned movies")
    
        # Send initial progress update
        if progress_callback:
            await progress_callback(f"Analyzing {len(owned_tmdb_ids)} movies for collections...", 0, len(owned_tmdb_ids))
    
        # Step 1: Find unique collection IDs using cached lookups
        seen_collections: Set[int] = set()
        owned_list = list(owned_tmdb_ids)
        processed_count = 0
    
        # Process in batches to avoid memory issues
        for i in range(0, len(owned_list), batch_size):
            batch = owned_list[i:i+batch_size]
        
            # Get collection IDs for batch
            for tmdb_id in batch:
                collection_id = await self.get_movie_collection_id(tmdb_id, use_cache=True)
                processed_count += 1
            
                # Send progress update every 100 movies or at batch completion
                if progress_callback and (processed_count % 100 == 0 or processed_count == len(owned_list)):
                    await progress_callback(
                        f"Scanning movies for collections... ({processed_count}/{len(owned_list)})", 
                        processed_count, 
                        len(owned_list)
                    )
            
                if not collection_id:
                    continue
            
                if collection_id in ignore_collections:
                    continue
                
                if collection_id not in seen_collections:
                    seen_collections.add(collection_id)
    
        logger.info(f"Found {len(seen_collections)} unique collections to fetch")
    
        # Send collection fetch progress update
        if progress_callback:
            await progress_callback(
                f"Found {len(seen_collections)} collections. Fetching from TMDB...", 
                0, 
                len(seen_collections)
            )
    
        # Step 2: Fetch ALL collections in parallel with concurrency limit
        semaphore = asyncio.Semaphore(settings.max_concurrent_api_calls if hasattr(settings, 'max_concurrent_api_calls') else 10)
        collection_ids_list = list(seen_collections)
    
        async def fetch_collection_with_progress(cid, idx):
            async with semaphore:
                # Send progress update for each collection fetch
                if progress_callback and idx % 3 == 0:
                    await progress_callback(
                        f"Fetching collection {idx + 1}/{len(collection_ids_list)}...", 
                        idx + 1, 
                        len(collection_ids_list)
                    )
                return await self.get_collection(cid, use_cache=True)
    
        if collection_ids_list:
            tasks = [fetch_collection_with_progress(cid, idx) for idx, cid in enumerate(collection_ids_list)]
            collections = await asyncio.gather(*tasks)
        else:
            collections = []
    
        # Send processing progress update
        if progress_callback:
            await progress_callback("Building missing movies list...", 0, 1)
    
        # Step 3: Build missing movies from fetched collections
        missing_movies: Dict[int, Dict] = {}
    
        for idx, collection in enumerate(collections):
            if not collection:
                continue
            
            # Send progress every 5 collections
            if progress_callback and idx % 5 == 0:
                await progress_callback(
                    f"Processing collection {idx + 1}/{len(collections)}...", 
                    idx + 1, 
                    len(collections)
                )
            
            collection_name = collection.get("name", "Unknown Collection")
            collection_id = collection.get("id")
            parts = collection.get("parts", [])
        
            for part in parts:
                part_id = part.get("id")
                if not part_id:
                    continue
            
                # Skip if already owned
                if part_id in owned_tmdb_ids:
                    continue
            
                # Skip ignored movies
                if part_id in ignore_movies:
                    continue
            
                # Skip future releases if setting enabled
                if hide_future:
                    release_date_str = part.get("release_date", "")
                    if release_date_str:
                        try:
                            release_date = datetime.fromisoformat(release_date_str[:10]).date()
                            if release_date > datetime.now().date():
                                logger.debug(f"Skipping future release: {part.get('title')} ({release_date})")
                                continue
                        except ValueError:
                            pass
            
                # Add to missing movies dict (deduplicate)
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
    
        # Convert to sorted list
        result = list(missing_movies.values())
        result.sort(key=lambda x: (x["collection_name"], x["year"]))
    
        # Final progress update
        if progress_callback:
            await progress_callback(
                f"Complete! Found {len(result)} missing movies", 
                len(result), 
                len(result)
            )
    
        logger.info(f"Found {len(result)} missing movies from {len(seen_collections)} collections "
                f"(API calls: {self._stats['api_calls']}, Cache hits: {self._stats['cache_hits']})")
    
        return result

    async def clear_cache(self, full_clear: bool = False):
        """Clear TMDB cache."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                if full_clear:
                    conn.execute("DELETE FROM movie_cache")
                    conn.execute("DELETE FROM collection_cache")
                    logger.info("Full cache cleared")
                else:
                    # Clear only old cache (older than 90 days)
                    conn.execute("DELETE FROM movie_cache WHERE cached_at < datetime('now', '-90 days')")
                    conn.execute("DELETE FROM collection_cache WHERE cached_at < datetime('now', '-90 days')")
                    logger.info("Old cache entries cleared")
                
                conn.commit()
            
            # Clear memory caches
            self._movie_collection_cache.clear()
            self._collection_cache.clear()
            
            # Reload recent entries
            self._load_memory_cache()
            
            return {"success": True, "message": "Cache cleared successfully"}
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return {"success": False, "error": str(e)}