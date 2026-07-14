#!/usr/bin/env python3
"""
Gaparr - Automatic collection gap filler for Radarr
Headless script that runs on schedule - no web UI needed.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional

import httpx
from tmdbv3api import TMDb, Movie as TMDbMovie

# ============================================================================
# Setup
# ============================================================================

# Create logs directory if it doesn't exist
LOG_DIR = Path("/app/logs")
LOG_DIR.mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "gaparr.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("gaparr")

# ============================================================================
# Load Configuration
# ============================================================================

CONFIG_FILE = Path("/app/config.json")

def load_config() -> dict:
    """Load configuration from config.json"""
    if not CONFIG_FILE.exists():
        logger.error(f"Config file not found: {CONFIG_FILE}")
        logger.error("Please copy config_example.json to config.json and edit it")
        sys.exit(1)
    
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
    
    # Validate required fields
    required = ["radarr_url", "radarr_api_key", "tmdb_api_key", "root_folder"]
    for field in required:
        if not config.get(field):
            logger.error(f"Missing required config field: {field}")
            sys.exit(1)

    # ADD VALIDATION FOR NEW FIELDS:
    # Validate max_collection_size is a positive integer if set
    if "max_collection_size" in config:
        try:
            size = int(config["max_collection_size"])
            if size < 0:
                logger.error("max_collection_size must be a positive integer or 0 to disable")
                sys.exit(1)
            config["max_collection_size"] = size
        except (ValueError, TypeError):
            logger.error("max_collection_size must be a number")
            sys.exit(1)
    
    # Validate ignored_collections is a list if set
    if "ignored_collections" in config:
        if not isinstance(config["ignored_collections"], list):
            logger.error("ignored_collections must be a list of collection names")
            sys.exit(1)
    
    # Validate ignored_genres is a list if set
    if "ignored_genres" in config:
        if not isinstance(config["ignored_genres"], list):
            logger.error("ignored_genres must be a list of genre names")
            sys.exit(1)
    
    # Validate min_runtime is a positive integer if set
    if "min_runtime" in config:
        try:
            runtime = int(config["min_runtime"])
            if runtime < 0:
                logger.error("min_runtime must be a positive integer or 0 to disable")
                sys.exit(1)
            config["min_runtime"] = runtime
        except (ValueError, TypeError):
            logger.error("min_runtime must be a number")
            sys.exit(1)
    
    # Set defaults for optional fields
    config.setdefault("ignored_genres", [])
    config.setdefault("ignored_collections", [])
    config.setdefault("max_collection_size", 0)
    config.setdefault("min_runtime", 0)

    return config

# ============================================================================
# Radarr Client
# ============================================================================

class RadarrClient:
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}

    async def get_root_folders(self):
        """Get available root folders from Radarr."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"{self.url}/api/v3/rootfolder", headers=self.headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch root folders: {e}")
            return []

    async def get_root_folder_path(self, configured_path: str):
        """Get the exact root folder path from Radarr that matches the configured path."""
        root_folders = await self.get_root_folders()
        
        if not root_folders:
            logger.error("No root folders found in Radarr")
            return None
        
        # Normalize the configured path for comparison
        configured_normalized = configured_path.replace('\\\\', '\\').replace('/', '\\').lower().rstrip('\\')
        
        for folder in root_folders:
            folder_path = folder.get('path', '')
            folder_normalized = folder_path.replace('/', '\\').lower().rstrip('\\')
            
            if folder_normalized == configured_normalized:
                logger.info(f"Found matching root folder: {folder_path}")
                return folder_path
        
        logger.error(f"Root folder '{configured_path}' not found in Radarr")
        logger.info("Available root folders in Radarr:")
        for folder in root_folders:
            logger.info(f"  - {folder.get('path')}")
        return None
    
    async def get_movies(self) -> List[Dict]:
        """Fetch all movies from Radarr"""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.url}/api/v3/movie", headers=self.headers)
            resp.raise_for_status()
            return resp.json()
    
    async def add_movie(self, tmdb_id: int, title: str, root_folder: str) -> bool:
        """Add a movie to Radarr"""
        # First, get quality profiles
        async with httpx.AsyncClient(timeout=30) as client:
            profiles_resp = await client.get(f"{self.url}/api/v3/qualityprofile", headers=self.headers)
            profiles = profiles_resp.json()
            
            if not profiles:
                logger.error("No quality profiles found in Radarr")
                return False
            
            quality_profile_id = profiles[0].get("id")
            
            payload = {
                "tmdbId": tmdb_id,
                "title": title,
                "qualityProfileId": quality_profile_id,
                "rootFolderPath": root_folder,
                "minimumAvailability": "released",
                "monitored": True,
                "addOptions": {
                    "monitor": "movieOnly",
                    "searchForMovie": True
                }
            }
            
            resp = await client.post(f"{self.url}/api/v3/movie", headers=self.headers, json=payload)
            resp.raise_for_status()
            return True

# ============================================================================
# TMDB Service
# ============================================================================

class TMDBService:
    def __init__(self, api_key: str):
        tmdb = TMDb()
        tmdb.api_key = api_key
        self.movie_api = TMDbMovie()
    
    def get_movie_collection_id(self, tmdb_id: int) -> int:
        """Get collection ID for a movie, or None if not in collection"""
        try:
            movie = self.movie_api.details(tmdb_id)
            collection = getattr(movie, "belongs_to_collection", None)
            if collection:
                return collection.get("id")
            return None
        except Exception as e:
            logger.debug(f"Failed to get collection for {tmdb_id}: {e}")
            return None
    
    def get_collection_details(self, collection_id: int) -> tuple:
        """
        Get collection details including name and movies.
        Returns: (collection_name, list_of_movies)
        """
        try:
            import requests
            url = f"https://api.themoviedb.org/3/collection/{collection_id}"
            params = {"api_key": self.movie_api.api_key, "language": "en-US"}
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        
            collection_name = data.get("name", "Unknown")
            movies = data.get("parts", [])
        
            return collection_name, movies
        except Exception as e:
            logger.warning(f"Failed to get collection {collection_id}: {e}")
            return "Unknown", []

     # ADD THIS NEW METHOD:
    def is_collection_ignored(self, collection_name: str, ignored_list: List[str]) -> bool:
        """Check if a collection should be ignored (case-insensitive partial match)"""
        if not ignored_list:
            return False
        
        collection_lower = collection_name.lower()
        for ignored in ignored_list:
            if ignored.lower() in collection_lower:
                return True
        return False
    
    def get_movie_genres(self, tmdb_id: int) -> List[str]:
        """Get genre names for a movie"""
        try:
            movie = self.movie_api.details(tmdb_id)
            genres = getattr(movie, "genres", [])
            return [g.get("name", "") for g in genres if g.get("name")]
        except Exception as e:
            logger.debug(f"Failed to get genres for {tmdb_id}: {e}")
            return []
    
    def get_movie_runtime(self, tmdb_id: int) -> Optional[int]:
        """Get runtime in minutes for a movie, or None if not available"""
        try:
            movie = self.movie_api.details(tmdb_id)
            runtime = getattr(movie, "runtime", None)
            return runtime if runtime and runtime > 0 else None
        except Exception as e:
            logger.debug(f"Failed to get runtime for {tmdb_id}: {e}")
            return None

# ============================================================================
# Main Logic
# ============================================================================

async def main():
    logger.info("=" * 50)
    logger.info("Gaparr Starting")
    logger.info("=" * 50)
    
    # Load config
    config = load_config()
    logger.info(f"Radarr URL: {config['radarr_url']}")
    logger.info(f"Daily limit: {config['daily_limit']}")
    logger.info(f"Auto-add: {config['auto_add']}")
    logger.info(f"Hide future releases: {config['hide_future']}")
    logger.info(f"Min runtime: {config.get('min_runtime', 0)} minutes")
    logger.info(f"Max collection size: {config.get('max_collection_size', 0)}")
    
    # Initialize clients
    radarr = RadarrClient(config["radarr_url"], config["radarr_api_key"])
    tmdb = TMDBService(config["tmdb_api_key"])
    
    # Get the correct root folder path from Radarr
    root_path = await radarr.get_root_folder_path(config["root_folder"])
    if not root_path:
        logger.error("Could not find a valid root folder in Radarr. Please check your root_folder setting.")
        sys.exit(1)
    logger.info(f"Using Radarr root folder: {root_path}")
    
    # Step 1: Get movies from Radarr
    logger.info("Step 1: Fetching movies from Radarr...")
    radarr_movies = await radarr.get_movies()
    owned_tmdb_ids = set()
    for movie in radarr_movies:
        tmdb_id = movie.get("tmdbId")
        if tmdb_id:
            owned_tmdb_ids.add(tmdb_id)
    
    logger.info(f"Found {len(owned_tmdb_ids)} movies in Radarr")
    
    # Step 2: Find unique collection IDs from owned movies
    logger.info("Step 2: Finding collection IDs from your movies...")
    collection_ids = set()
    for tmdb_id in owned_tmdb_ids:
        coll_id = tmdb.get_movie_collection_id(tmdb_id)
        if coll_id:
            collection_ids.add(coll_id)
    
    logger.info(f"Found {len(collection_ids)} unique collections")
    
    # Step 3: Fetch all collection details
    logger.info("Step 3: Fetching collection details from TMDB...")
    all_missing = {}
    
    # Get config options for filtering
    max_collection_size = config.get("max_collection_size")
    ignored_collections = config.get("ignored_collections", [])

    # Track collection data for reporting
    collection_data = {}  # collection_name -> {owned: [], skipped_count: 0, reason: ""}
    
    for coll_id in collection_ids:
        logger.info(f"  Fetching collection ID: {coll_id}")
        collection_name, movies = tmdb.get_collection_details(coll_id)

        # Initialize tracking for this collection
        collection_data[collection_name] = {
            "owned_movies": [],
            "skipped_count": 0,
            "skipped_actionable": 0,
            "skip_reason": "",
            "skip_reasons": []
        }
        
        # CHECK 1: Skip by name (ignored collections)
        if tmdb.is_collection_ignored(collection_name, ignored_collections):
            logger.info(f"  Skipping ignored collection: {collection_name}")
            collection_data[collection_name]["skip_reason"] = "Ignored by name"
            continue
        
        # CHECK 2: Skip by size (large collections)
        if max_collection_size and len(movies) > max_collection_size:
            logger.info(f"  Skipping large collection: {collection_name} ({len(movies)} movies > {max_collection_size} limit)")
            collection_data[collection_name]["skip_reason"] = f"Collection size ({len(movies)} > {max_collection_size} limit)"
            continue
        
        for movie in movies:
            movie_id = movie.get("id")
            if not movie_id:
                continue
            
            # Skip if already owned - track it for the report
            if movie_id in owned_tmdb_ids:
                # Find the movie title to add to owned list
                movie_title = movie.get("title", "Unknown")
                release_year = movie.get("release_date", "")[:4] if movie.get("release_date") else "N/A"
                collection_data[collection_name]["owned_movies"].append(f"{movie_title} ({release_year})")
                continue
            
            # Skip future releases if setting enabled
            if config.get("hide_future", True):
                release_date = movie.get("release_date", "")
                if not release_date:
                    # No release date - skip it (status rumored/unconfirmed)
                    logger.debug(f"Skipping movie with no release date: {movie.get('title')}")
                    collection_data[collection_name]["skipped_count"] += 1
                    continue
                try:
                    release_date_obj = datetime.strptime(release_date[:10], "%Y-%m-%d")
                    if release_date_obj > datetime.now():
                        logger.debug(f"Skipping future release: {movie.get('title')} ({release_date})")
                        collection_data[collection_name]["skipped_count"] += 1
                        continue
                except Exception as e:
                    logger.debug(f"Failed to parse release date '{release_date}' for {movie.get('title')}: {e}")
                    continue
            
            # Check genre filter
            ignored_genres = config.get("ignored_genres", [])
            if ignored_genres:
                genres = tmdb.get_movie_genres(movie_id)
                if any(genre in ignored_genres for genre in genres):
                    logger.debug(f"Skipping movie with ignored genre: {movie.get('title')} (Genres: {', '.join(genres)})")
                    collection_data[collection_name]["skipped_count"] += 1
                    collection_data[collection_name]["skipped_actionable"] += 1
                    if "Ignored genre" not in collection_data[collection_name]["skip_reasons"]:
                        collection_data[collection_name]["skip_reasons"].append("Ignored genre")
                    continue

            # Check minimum runtime
            min_runtime = config.get("min_runtime", 0)
            if min_runtime > 0:
                runtime = tmdb.get_movie_runtime(movie_id)
                if runtime is None or runtime < min_runtime:
                    logger.debug(f"Skipping short movie: {movie.get('title')} ({runtime or 'unknown'} minutes)")
                    collection_data[collection_name]["skipped_count"] += 1
                    collection_data[collection_name]["skipped_actionable"] += 1 
                    if "Short runtime" not in collection_data[collection_name]["skip_reasons"]:
                        collection_data[collection_name]["skip_reasons"].append("Short runtime")
                    continue
            
            # Add to missing dict (deduplicate)
            if movie_id not in all_missing:
                all_missing[movie_id] = {
                    "tmdb_id": movie_id,
                    "title": movie.get("title", "Unknown"),
                    "year": movie.get("release_date", "")[:4] if movie.get("release_date") else "N/A",
                    "collection_name": collection_name,
                    "release_date": movie.get("release_date", "")
                }
    
    # ========================================================================
    # Collection Inventory Report
    # ========================================================================
    # Filter to collections that have owned movies AND skipped movies
    collections_with_skips = {
        name: data for name, data in collection_data.items()
        if data["owned_movies"] and data["skipped_actionable"] > 0
    }
    
    if collections_with_skips:
        logger.info("=" * 50)
        logger.info("COLLECTION INVENTORY (MOVIES YOU OWN)")
        logger.info("=" * 50)
        
        for collection_name, data in collections_with_skips.items():
            logger.info(f"\n- {collection_name}")
            logger.info(f"   Movies you own ({len(data['owned_movies'])}):")
            
            # Show owned movies (truncate if more than 15)
            owned_list = data["owned_movies"]
            if len(owned_list) <= 15:
                for movie in owned_list:
                    logger.info(f"     - {movie}")
            else:
                for movie in owned_list[:15]:
                    logger.info(f"     - {movie}")
                logger.info(f"     ... and {len(owned_list) - 15} more")
            
            # Show skipped count with reason
            if data["skip_reason"]:
                logger.info(f"   ! {data['skipped_actionable']} missing movies were skipped ({data['skip_reason']})")
            else:
                # Build reason string from skip_reasons list
                reason_text = ""
                if data["skip_reasons"]:
                    # Join unique reasons with " & "
                    reason_text = " (" + " & ".join(data["skip_reasons"]) + ")"
                
                # Show actionable skips, mention if future skips were also skipped
                if data["skipped_count"] > data["skipped_actionable"]:
                    future_skips = data["skipped_count"] - data["skipped_actionable"]
                    logger.info(f"   ! {data['skipped_actionable']} missing movies were skipped by your filters{reason_text} ({future_skips} future/unreleased movies not shown)")
                else:
                    logger.info(f"   ! {data['skipped_actionable']} missing movies were skipped by your filters{reason_text}")
        
        logger.info("=" * 50)
        total_actionable = sum(data["skipped_actionable"] for data in collections_with_skips.values())
        logger.info(f"Collections with skipped movies: {len(collections_with_skips)}")
        logger.info(f"Total skipped movies: {total_actionable}")
        logger.info("=" * 50)
        logger.info("")
    
    # ========================================================================
    # Missing Movies List (existing code)
    # ========================================================================
    
    missing_movies = list(all_missing.values())
    missing_movies.sort(key=lambda x: x["collection_name"])
    
    logger.info("=" * 50)
    logger.info(f"FOUND {len(missing_movies)} MISSING MOVIES")
    logger.info("=" * 50)
    
    for movie in missing_movies:
        # Get genres for display
        genres = tmdb.get_movie_genres(movie["tmdb_id"])
        genres_str = f" (Genres: {', '.join(genres)})" if genres else ""
        logger.info(f"  - {movie['title']} ({movie['year']}) from {movie['collection_name']}{genres_str}")
    
    # ADD THIS OPTIONAL ENHANCEMENT:
    logger.info("=" * 50)
    logger.info("FILTERING SUMMARY")
    logger.info("=" * 50)

    # Log which collections were ignored by name
    if ignored_collections:
        logger.info(f"Ignored collections by name: {', '.join(ignored_collections)}")
    else:
        logger.info("No collections ignored by name")
    
    # Log the size limit that was applied
    if max_collection_size:
        logger.info(f"Collections with > {max_collection_size} movies were skipped")
    else:
        logger.info("No collection size limit applied")

    # Log ignored genres
    ignored_genres = config.get("ignored_genres", [])
    if ignored_genres:
        logger.info(f"Ignored genres: {', '.join(ignored_genres)}")
    else:
        logger.info("No genres ignored")
    
    # Step 4: Add movies to Radarr (up to daily limit)
    if config.get("auto_add", False):
        limit = config.get("daily_limit", 5)
        to_add = missing_movies[:limit]
        
        logger.info("=" * 50)
        logger.info(f"Adding up to {limit} movies to Radarr...")
        
        added_count = 0
        for movie in to_add:
            try:
                logger.info(f"  Adding: {movie['title']}")
                success = await radarr.add_movie(
                    movie["tmdb_id"],
                    movie["title"],
                    root_path 
                )
                if success:
                    added_count += 1
                    logger.info(f"    ✓ Added successfully")
                else:
                    logger.warning(f"    ✗ Failed to add")
            except Exception as e:
                logger.error(f"    ✗ Error: {e}")
        
        logger.info(f"Added {added_count} of {len(to_add)} movies")
    else:
        logger.info("Auto-add disabled. Run with auto_add: true to automatically add movies.")
    
    # Step 5: Save results to log file for dashboard to read (optional)
    results_file = Path("/app/logs/last_scan.json")
    with open(results_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_missing": len(missing_movies),
            "missing_movies": missing_movies[:100]  # Save first 100 for display
        }, f, indent=2)
    
    logger.info("=" * 50)
    logger.info("Gaparr Complete")
    logger.info("=" * 50)

# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())