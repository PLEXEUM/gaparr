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
            
            # Cache Settings (NEW)
            "cache_ttl_days": 30,           # How long to keep cache entries (days)
            "cache_cleanup_days": 90,       # Auto-clean cache older than this (days)
            "batch_size": 20,               # Movies to process per batch
            "max_concurrent_api_calls": 10,  # Max concurrent TMDB API requests
            "api_rate_limit": 50,           # TMDB API calls per second
            "enable_cache": True,            # Master cache switch
            "enable_rate_limiting": True,    # Master rate limiting switch
            
            # Performance Settings (NEW)
            "prewarm_cache_on_startup": False,  # Load popular collections at startup
            "parallel_collection_fetching": True,  # Enable parallel collection fetching
            
            # Logging Settings
            "log_level": "INFO",             # DEBUG, INFO, WARNING, ERROR
            "log_max_lines": 1000,           # Maximum lines to keep in memory
            
            # App Settings
            "first_run": True,
            "port": 7117,
            "host": "0.0.0.0"
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
    
    # Radarr Getters
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
    
    # TMDB Getters
    @property
    def tmdb_api_key(self) -> str:
        return self._settings.get("tmdb_api_key", "")
    
    @property
    def tmdb_configured(self) -> bool:
        return bool(self.tmdb_api_key)
    
    # Sync Getters
    @property
    def daily_limit(self) -> int:
        return self._settings.get("daily_limit", 5)
    
    @property
    def sync_time(self) -> str:
        return self._settings.get("sync_time", "02:00")
    
    @property
    def hide_future_releases(self) -> bool:
        return self._settings.get("hide_future_releases", True)
    
    # Cache Getters (NEW)
    @property
    def cache_ttl_days(self) -> int:
        return self._settings.get("cache_ttl_days", 30)
    
    @property
    def cache_cleanup_days(self) -> int:
        return self._settings.get("cache_cleanup_days", 90)
    
    @property
    def batch_size(self) -> int:
        return self._settings.get("batch_size", 20)
    
    @property
    def max_concurrent_api_calls(self) -> int:
        return self._settings.get("max_concurrent_api_calls", 10)
    
    @property
    def api_rate_limit(self) -> int:
        return self._settings.get("api_rate_limit", 50)
    
    @property
    def enable_cache(self) -> bool:
        return self._settings.get("enable_cache", True)
    
    @property
    def enable_rate_limiting(self) -> bool:
        return self._settings.get("enable_rate_limiting", True)
    
    # Performance Getters (NEW)
    @property
    def prewarm_cache_on_startup(self) -> bool:
        return self._settings.get("prewarm_cache_on_startup", False)
    
    @property
    def parallel_collection_fetching(self) -> bool:
        return self._settings.get("parallel_collection_fetching", True)
    
    # Logging Getters (NEW)
    @property
    def log_level(self) -> str:
        return self._settings.get("log_level", "INFO")
    
    @property
    def log_max_lines(self) -> int:
        return self._settings.get("log_max_lines", 1000)
    
    # App Getters
    @property
    def first_run(self) -> bool:
        return self._settings.get("first_run", True)
    
    @property
    def port(self) -> int:
        return self._settings.get("port", 7117)
    
    @property
    def host(self) -> str:
        return self._settings.get("host", "0.0.0.0")
    
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
    
    def set_cache_config(
        self, 
        ttl_days: int = None, 
        cleanup_days: int = None, 
        batch_size: int = None,
        max_concurrent: int = None,
        rate_limit: int = None,
        enable_cache: bool = None,
        enable_rate_limiting: bool = None
    ) -> None:
        """Save cache configuration."""
        if ttl_days is not None:
            self._settings["cache_ttl_days"] = ttl_days
        if cleanup_days is not None:
            self._settings["cache_cleanup_days"] = cleanup_days
        if batch_size is not None:
            self._settings["batch_size"] = batch_size
        if max_concurrent is not None:
            self._settings["max_concurrent_api_calls"] = max_concurrent
        if rate_limit is not None:
            self._settings["api_rate_limit"] = rate_limit
        if enable_cache is not None:
            self._settings["enable_cache"] = enable_cache
        if enable_rate_limiting is not None:
            self._settings["enable_rate_limiting"] = enable_rate_limiting
        self._save()
    
    def set_performance_config(
        self,
        prewarm_cache: bool = None,
        parallel_fetching: bool = None,
        log_level: str = None
    ) -> None:
        """Save performance configuration."""
        if prewarm_cache is not None:
            self._settings["prewarm_cache_on_startup"] = prewarm_cache
        if parallel_fetching is not None:
            self._settings["parallel_collection_fetching"] = parallel_fetching
        if log_level is not None:
            self._settings["log_level"] = log_level
        self._save()
    
    def get_all(self) -> Dict[str, Any]:
        """Get all settings (for API response, redacting sensitive data)."""
        return {
            # Radarr settings
            "radarr_url": self.radarr_url,
            "radarr_configured": self.radarr_configured,
            "root_folder_path": self.root_folder_path,
            
            # TMDB settings
            "tmdb_configured": self.tmdb_configured,
            
            # Sync settings
            "daily_limit": self.daily_limit,
            "sync_time": self.sync_time,
            "hide_future_releases": self.hide_future_releases,
            
            # Cache settings
            "cache_ttl_days": self.cache_ttl_days,
            "cache_cleanup_days": self.cache_cleanup_days,
            "batch_size": self.batch_size,
            "max_concurrent_api_calls": self.max_concurrent_api_calls,
            "api_rate_limit": self.api_rate_limit,
            "enable_cache": self.enable_cache,
            "enable_rate_limiting": self.enable_rate_limiting,
            
            # Performance settings
            "prewarm_cache_on_startup": self.prewarm_cache_on_startup,
            "parallel_collection_fetching": self.parallel_collection_fetching,
            
            # Logging settings
            "log_level": self.log_level,
            "log_max_lines": self.log_max_lines,
            
            # App settings
            "first_run": self.first_run,
            "port": self.port,
            "host": self.host,
            "is_configured": self.is_fully_configured
        }
    
    def reset_to_defaults(self) -> None:
        """Reset all settings to default values."""
        self._settings = self._load()  # Reload defaults
        self._save()
        logger.info("Settings reset to defaults")


# Singleton instance
settings = Settings()