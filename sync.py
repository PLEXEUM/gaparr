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
from typing import Dict, List, Set

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
    
    return config

# ============================================================================
# Radarr Client
# ============================================================================

class RadarrClient:
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}
    
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
    
    # Initialize clients
    radarr = RadarrClient(config["radarr_url"], config["radarr_api_key"])
    tmdb = TMDBService(config["tmdb_api_key"])
    
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
    
    for coll_id in collection_ids:
        logger.info(f"  Fetching collection ID: {coll_id}")
        collection_name, movies = tmdb.get_collection_details(coll_id)
        
        for movie in movies:
            movie_id = movie.get("id")
            if not movie_id:
                continue
            
            # Skip if already owned
            if movie_id in owned_tmdb_ids:
                continue
            
            # Skip future releases if setting enabled
            if config.get("hide_future", True):
                release_date = movie.get("release_date", "")
                if not release_date:
                    # No release date - skip it (status rumored/unconfirmed)
                    logger.debug(f"Skipping movie with no release date: {movie.get('title')}")
                    continue
                try:
                    release_date_obj = datetime.strptime(release_date[:10], "%Y-%m-%d")
                    if release_date_obj > datetime.now():
                        logger.debug(f"Skipping future release: {movie.get('title')} ({release_date})")
                        continue
                except Exception as e:
                    logger.debug(f"Failed to parse release date '{release_date}' for {movie.get('title')}: {e}")
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
    
    missing_movies = list(all_missing.values())
    missing_movies.sort(key=lambda x: x["collection_name"])
    
    logger.info("=" * 50)
    logger.info(f"FOUND {len(missing_movies)} MISSING MOVIES")
    logger.info("=" * 50)
    
    for movie in missing_movies:
        logger.info(f"  - {movie['title']} ({movie['year']}) from {movie['collection_name']}")
    
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
                    config["root_folder"]
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