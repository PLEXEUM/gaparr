"""Sync service for daily quota tracking and Radarr integration."""

import json
import os
import logging
from datetime import datetime, date
from typing import List, Dict, Any, Set, Optional
from pathlib import Path

from app.services.radarr_service import RadarrClient
from app.services.tmdb_service import TMDBService

logger = logging.getLogger(__name__)


class SyncService:
    """Manages daily sync quotas and coordinates Radarr + TMDB."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.state_file = self.data_dir / "sync_state.json"
        self._state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Load sync state from JSON file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load state file: {e}")
        return {
            "last_sync_date": None,
            "synced_today": 0,
            "synced_movies": [],  # List of TMDB IDs synced
            "ignored_collections": [],  # List of collection IDs
            "ignored_movies": []  # List of TMDB IDs
        }

    def _save_state(self) -> None:
        """Save sync state to JSON file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(self._state, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save state file: {e}")

    def _reset_daily_counter(self) -> None:
        """Reset daily counter if it's a new day."""
        today = date.today().isoformat()
        if self._state["last_sync_date"] != today:
            self._state["last_sync_date"] = today
            self._state["synced_today"] = 0
            self._state["synced_movies"] = []
            logger.info(f"Reset daily counter for {today}")
            self._save_state()

    def get_remaining_today(self, daily_limit: int) -> int:
        """Get how many movies can still be synced today."""
        self._reset_daily_counter()
        return max(0, daily_limit - self._state["synced_today"])

    def mark_synced(self, tmdb_id: int) -> None:
        """Mark a movie as synced (added to Radarr)."""
        self._reset_daily_counter()
        if tmdb_id not in self._state["synced_movies"]:
            self._state["synced_today"] += 1
            self._state["synced_movies"].append(tmdb_id)
            self._save_state()
            logger.info(f"Marked TMDB {tmdb_id} as synced ({self._state['synced_today']} today)")

    def is_synced(self, tmdb_id: int) -> bool:
        """Check if a movie has already been synced."""
        return tmdb_id in self._state.get("synced_movies", [])

    def add_ignored_collection(self, collection_id: int) -> None:
        """Add a collection to ignore list."""
        if collection_id not in self._state["ignored_collections"]:
            self._state["ignored_collections"].append(collection_id)
            self._save_state()
            logger.info(f"Added collection {collection_id} to ignore list")

    def remove_ignored_collection(self, collection_id: int) -> None:
        """Remove a collection from ignore list."""
        if collection_id in self._state["ignored_collections"]:
            self._state["ignored_collections"].remove(collection_id)
            self._save_state()
            logger.info(f"Removed collection {collection_id} from ignore list")

    def add_ignored_movie(self, tmdb_id: int) -> None:
        """Add a movie to ignore list."""
        if tmdb_id not in self._state["ignored_movies"]:
            self._state["ignored_movies"].append(tmdb_id)
            self._save_state()
            logger.info(f"Added movie {tmdb_id} to ignore list")

    def remove_ignored_movie(self, tmdb_id: int) -> None:
        """Remove a movie from ignore list."""
        if tmdb_id in self._state["ignored_movies"]:
            self._state["ignored_movies"].remove(tmdb_id)
            self._save_state()
            logger.info(f"Removed movie {tmdb_id} from ignore list")

    def get_ignored_collections(self) -> List[int]:
        """Get list of ignored collection IDs."""
        return self._state.get("ignored_collections", [])

    def get_ignored_movies(self) -> List[int]:
        """Get list of ignored movie TMDB IDs."""
        return self._state.get("ignored_movies", [])

    async def sync_missing_movies(
        self,
        radarr_client: RadarrClient,
        tmdb_service: TMDBService,
        root_folder_path: str,
        daily_limit: int,
        hide_future: bool = True
    ) -> Dict[str, Any]:
        """
        Find missing collection movies and add them to Radarr, respecting daily limit.

        Returns:
            Dict with sync results: added_count, skipped_count, missing_movies list
        """
        # Reset daily counter if needed
        self._reset_daily_counter()

        # Get all movies currently in Radarr
        logger.info("Fetching movies from Radarr...")
        radarr_movies = await radarr_client.get_movies()
        owned_tmdb_ids: Set[int] = set()

        for movie in radarr_movies:
            tmdb_id = movie.get("tmdbId")
            if tmdb_id:
                owned_tmdb_ids.add(tmdb_id)

        logger.info(f"Found {len(owned_tmdb_ids)} movies in Radarr")

        # Find missing collection movies
        logger.info("Finding collection gaps from TMDB...")
        missing_movies = await tmdb_service.find_collection_gaps(
            owned_tmdb_ids=owned_tmdb_ids,
            hide_future=hide_future,
            ignore_collections=self.get_ignored_collections(),
            ignore_movies=self.get_ignored_movies()
        )

        # Filter out already synced movies
        unsynced_missing = [
            m for m in missing_movies
            if not self.is_synced(m["tmdb_id"])
        ]

        logger.info(f"Found {len(missing_movies)} missing, {len(unsynced_missing)} unsynced")

        # Apply daily limit
        remaining = self.get_remaining_today(daily_limit)
        to_add = unsynced_missing[:remaining]

        added_count = 0
        failed_count = 0
        added_movies = []

        for movie in to_add:
            try:
                logger.info(f"Adding to Radarr: {movie['title']} ({movie['year']})")
                result = await radarr_client.add_movie(
                    tmdb_id=movie["tmdb_id"],
                    title=movie["title"],
                    root_folder_path=root_folder_path
                )
                self.mark_synced(movie["tmdb_id"])
                added_count += 1
                added_movies.append(movie)
                logger.info(f"Successfully added: {movie['title']}")
            except Exception as e:
                logger.error(f"Failed to add {movie['title']}: {e}")
                failed_count += 1

        return {
            "added_count": added_count,
            "failed_count": failed_count,
            "remaining_today": remaining - added_count,
            "total_missing": len(missing_movies),
            "added_movies": added_movies,
            "pending_movies": unsynced_missing[remaining:] if remaining < len(unsynced_missing) else []
        }