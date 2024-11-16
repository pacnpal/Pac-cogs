"""Module for managing database schema"""

import logging
import sqlite3
from pathlib import Path
from typing import List

logger = logging.getLogger("DBSchemaManager")


class DatabaseSchemaManager:
    """Manages database schema creation and updates"""

    SCHEMA_VERSION = 1  # Increment when schema changes

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def initialize_schema(self) -> None:
        """Initialize or update the database schema"""
        try:
            self._create_schema_version_table()
            current_version = self._get_schema_version()

            if current_version < self.SCHEMA_VERSION:
                self._apply_migrations(current_version)
                self._update_schema_version()

        except sqlite3.Error as e:
            logger.error(f"Schema initialization error: {e}")
            raise

    def _create_schema_version_table(self) -> None:
        """Create schema version tracking table"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
            """
            )
            # Insert initial version if table is empty
            cursor.execute("INSERT OR IGNORE INTO schema_version VALUES (0)")
            conn.commit()

    def _get_schema_version(self) -> int:
        """Get current schema version"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT version FROM schema_version LIMIT 1")
            result = cursor.fetchone()
            return result[0] if result else 0

    def _update_schema_version(self) -> None:
        """Update schema version to current"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE schema_version SET version = ?", (self.SCHEMA_VERSION,)
            )
            conn.commit()

    def _apply_migrations(self, current_version: int) -> None:
        """Apply necessary schema migrations"""
        migrations = self._get_migrations(current_version)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for migration in migrations:
                try:
                    cursor.executescript(migration)
                    conn.commit()
                except sqlite3.Error as e:
                    logger.error(f"Migration failed: {e}")
                    raise

    def _get_migrations(self, current_version: int) -> List[str]:
        """Get list of migrations to apply"""
        migrations = []

        # Version 0 to 1: Initial schema
        if current_version < 1:
            migrations.append(
                """
                CREATE TABLE IF NOT EXISTS archived_videos (
                    original_url TEXT PRIMARY KEY,
                    discord_url TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_size INTEGER,
                    duration INTEGER,
                    format TEXT,
                    resolution TEXT,
                    bitrate INTEGER
                );
                
                CREATE INDEX IF NOT EXISTS idx_guild_channel 
                ON archived_videos(guild_id, channel_id);
                
                CREATE INDEX IF NOT EXISTS idx_archived_at 
                ON archived_videos(archived_at);
            """
            )

        # Add more migrations here as schema evolves
        # if current_version < 2:
        #     migrations.append(...)

        return migrations
