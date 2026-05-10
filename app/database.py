"""Database management for TMDB cache and migrations."""

import sqlite3
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1

def get_db_connection(db_path: Path):
    """Get database connection with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_schema_version(db_path: Path) -> int:
    """Get current schema version from database."""
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT version FROM schema_version WHERE id = 1")
            row = cursor.fetchone()
            return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0

def migrate_database(db_path: Path, target_version: int = CURRENT_SCHEMA_VERSION):
    """Migrate database to target version."""
    current = get_schema_version(db_path)
    
    if current >= target_version:
        return
    
    logger.info(f"Migrating database from version {current} to {target_version}")
    
    with sqlite3.connect(db_path) as conn:
        if current == 0:
            # Initial schema creation handled by TMDBService._init_database()
            # Just create schema_version table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL,
                    migrated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, 1)")
            conn.commit()
        
        # Add future migrations here
        # if current == 1:
        #     conn.execute("ALTER TABLE movie_cache ADD COLUMN new_column TEXT")
        #     conn.execute("UPDATE schema_version SET version = 2 WHERE id = 1")
        
        logger.info(f"Database migrated to version {target_version}")

def validate_cache_integrity(db_path: Path) -> Dict[str, Any]:
    """Validate cache database integrity."""
    issues = []
    
    try:
        with sqlite3.connect(db_path) as conn:
            # Check for corrupt indexes
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            if result and result[0] != "ok":
                issues.append(f"Integrity check failed: {result[0]}")
            
            # Check for orphaned records
            cursor = conn.execute("""
                SELECT COUNT(*) FROM movie_cache 
                WHERE tmdb_id IS NULL
            """)
            if cursor.fetchone()[0] > 0:
                issues.append("Found movie records with NULL tmdb_id")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "db_path": str(db_path)
        }
    except Exception as e:
        return {
            "valid": False,
            "issues": [f"Failed to validate: {str(e)}"],
            "db_path": str(db_path)
        }