"""Application settings - stored in JSON file, no .env required."""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class Settings:
    """Application settings loaded from/saved to JSON file."""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.settings_file = self.data_dir / "settings.json"
        self._settings: Dict[str, Any] = self._load()
    
    def _load(self) -> Dict[str, Any]:
        """Load settings from JSON file."""
        default_settings = {
            # Radarr Configuration
            "radarr_url": "",
            "radarr_api_key": "",
            "radarr_configured": False,
            "root_folder_path": "",
            
            # TMDB Configuration
            "tmdb_api_key": "",
            "tmdb_configured": False,
            
            # Sync Settings
            "daily_limit": 5,
            "sync_time": "02:00",
            "hide_future_releases": True,
            
            # App Settings
            "first_run": True
        }
        
        if self.settings_file.exists():
            try:
                with open(self.settings_file, "r") as f:
                    loaded = json.load(f)
                    # Merge with defaults (in case new keys added)
                    default_settings.update(loaded)
                    logger.info(f"Loaded settings from {self.settings_file}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load settings: {e}")
        
        return default_settings
    
    def _save(self) -> None:
        """Save settings to JSON file."""
        try:
            with open(self.settings_file, "w") as f:
                json.dump(self._settings, f, indent=2)
            logger.info(f"Saved settings to {self.settings_file}")
        except IOError as e:
            logger.error(f"Failed to save settings: {e}")
    
    # Getters
    @property
    def radarr_url(self) -> str:
        return self._settings.get("radarr_url", "")
    
    @property
    def radarr_api_key(self) -> str:
        return self._settings.get("radarr_api_key", "")
    
    @property
    def radarr_configured(self) -> bool:
        return bool(self.radarr_url and self.radarr_api_key)
    
    @property
    def root_folder_path(self) -> str:
        return self._settings.get("root_folder_path", "")
    
    @property
    def tmdb_api_key(self) -> str:
        return self._settings.get("tmdb_api_key", "")
    
    @property
    def tmdb_configured(self) -> bool:
        return bool(self.tmdb_api_key)
    
    @property
    def daily_limit(self) -> int:
        return self._settings.get("daily_limit", 5)
    
    @property
    def sync_time(self) -> str:
        return self._settings.get("sync_time", "02:00")
    
    @property
    def hide_future_releases(self) -> bool:
        return self._settings.get("hide_future_releases", True)
    
    @property
    def first_run(self) -> bool:
        return self._settings.get("first_run", True)
    
    @property
    def is_fully_configured(self) -> bool:
        """Check if all required settings are present."""
        return (self.radarr_configured and 
                self.tmdb_configured and 
                bool(self.root_folder_path))
    
    # Setters
    def set_radarr_config(self, url: str, api_key: str, root_folder: str) -> None:
        """Save Radarr configuration."""
        self._settings["radarr_url"] = url
        self._settings["radarr_api_key"] = api_key
        self._settings["root_folder_path"] = root_folder
        self._settings["first_run"] = False
        self._save()
    
    def set_tmdb_config(self, api_key: str) -> None:
        """Save TMDB configuration."""
        self._settings["tmdb_api_key"] = api_key
        self._settings["first_run"] = False
        self._save()
    
    def set_sync_config(self, daily_limit: int, sync_time: str, hide_future: bool) -> None:
        """Save sync configuration."""
        self._settings["daily_limit"] = daily_limit
        self._settings["sync_time"] = sync_time
        self._settings["hide_future_releases"] = hide_future
        self._settings["first_run"] = False
        self._save()
    
    def get_all(self) -> Dict[str, Any]:
        """Get all settings (for API response, redacting sensitive data)."""
        return {
            "radarr_url": self.radarr_url,
            "radarr_configured": self.radarr_configured,
            "root_folder_path": self.root_folder_path,
            "tmdb_configured": self.tmdb_configured,
            "daily_limit": self.daily_limit,
            "sync_time": self.sync_time,
            "hide_future_releases": self.hide_future_releases,
            "first_run": self.first_run,
            "is_configured": self.is_fully_configured
        }


# Singleton instance
settings = Settings()