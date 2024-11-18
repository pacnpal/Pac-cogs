"""Module for managing database schema"""

import logging
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional, TypedDict, ClassVar, Union
from enum import Enum, auto
from datetime import datetime

try:
    # Try relative imports first
    from ..utils.exceptions import DatabaseError, ErrorContext, ErrorSeverity
except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.utils.exceptions import DatabaseError, ErrorContext, ErrorSeverity

logger = logging.getLogger("DBSchemaManager")


class SchemaState(Enum):
    """Schema states"""

    UNINITIALIZED = auto()
    INITIALIZING = auto()
    READY = auto()
    MIGRATING = auto()
    ERROR = auto()


class MigrationType(Enum):
    """Migration types"""

    CREATE = auto()
    ALTER = auto()
    INDEX = auto()
    DATA = auto()


class SchemaVersion(TypedDict):
    """Type definition for schema version"""

    version: int
    last_updated: str
    migrations_applied: List[str]


class MigrationResult(TypedDict):
    """Type definition for migration result"""

    success: bool
    error: Optional[str]
    migration_type: str
    duration: float
    timestamp: str


class SchemaStatus(TypedDict):
    """Type definition for schema status"""

    state: str
    current_version: int
    target_version: int
    last_migration: Optional[str]
    error: Optional[str]
    initialized: bool


class DatabaseSchemaManager:
    """Manages database schema creation and updates"""

    SCHEMA_VERSION: ClassVar[int] = 1  # Increment when schema changes
    MIGRATION_TIMEOUT: ClassVar[float] = 30.0  # Seconds

    def __init__(self, db_path: Path) -> None:
        """
        Initialize schema manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.state = SchemaState.UNINITIALIZED
        self.last_error: Optional[str] = None
        self.last_migration: Optional[str] = None

    def initialize_schema(self) -> None:
        """
        Initialize or update the database schema.

        Raises:
            DatabaseError: If schema initialization fails
        """
        try:
            self.state = SchemaState.INITIALIZING
            self._create_schema_version_table()
            current_version = self._get_schema_version()

            if current_version < self.SCHEMA_VERSION:
                self.state = SchemaState.MIGRATING
                self._apply_migrations(current_version)
                self._update_schema_version()

            self.state = SchemaState.READY

        except sqlite3.Error as e:
            self.state = SchemaState.ERROR
            self.last_error = str(e)
            error = f"Schema initialization failed: {str(e)}"
            logger.error(error, exc_info=True)
            raise DatabaseError(
                error,
                context=ErrorContext(
                    "SchemaManager",
                    "initialize_schema",
                    {"current_version": current_version},
                    ErrorSeverity.CRITICAL,
                ),
            )

    def _create_schema_version_table(self) -> None:
        """
        Create schema version tracking table.

        Raises:
            DatabaseError: If table creation fails
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        migrations_applied TEXT
                    )
                    """
                )
                # Insert initial version if table is empty
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO schema_version (version, migrations_applied)
                    VALUES (0, '[]')
                    """
                )
                conn.commit()

        except sqlite3.Error as e:
            error = f"Failed to create schema version table: {str(e)}"
            logger.error(error, exc_info=True)
            raise DatabaseError(
                error,
                context=ErrorContext(
                    "SchemaManager",
                    "create_schema_version_table",
                    None,
                    ErrorSeverity.CRITICAL,
                ),
            )

    def _get_schema_version(self) -> int:
        """
        Get current schema version.

        Returns:
            Current schema version

        Raises:
            DatabaseError: If version query fails
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT version FROM schema_version LIMIT 1")
                result = cursor.fetchone()
                return result[0] if result else 0

        except sqlite3.Error as e:
            error = f"Failed to get schema version: {str(e)}"
            logger.error(error, exc_info=True)
            raise DatabaseError(
                error,
                context=ErrorContext(
                    "SchemaManager", "get_schema_version", None, ErrorSeverity.HIGH
                ),
            )

    def _update_schema_version(self) -> None:
        """
        Update schema version to current.

        Raises:
            DatabaseError: If version update fails
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE schema_version 
                    SET version = ?, last_updated = CURRENT_TIMESTAMP
                    """,
                    (self.SCHEMA_VERSION,),
                )
                conn.commit()

        except sqlite3.Error as e:
            error = f"Failed to update schema version: {str(e)}"
            logger.error(error, exc_info=True)
            raise DatabaseError(
                error,
                context=ErrorContext(
                    "SchemaManager",
                    "update_schema_version",
                    {"target_version": self.SCHEMA_VERSION},
                    ErrorSeverity.HIGH,
                ),
            )

    def _apply_migrations(self, current_version: int) -> None:
        """
        Apply necessary schema migrations.

        Args:
            current_version: Current schema version

        Raises:
            DatabaseError: If migrations fail
        """
        migrations = self._get_migrations(current_version)
        results: List[MigrationResult] = []

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for migration in migrations:
                start_time = datetime.utcnow()
                try:
                    cursor.executescript(migration)
                    conn.commit()
                    self.last_migration = migration

                    results.append(
                        MigrationResult(
                            success=True,
                            error=None,
                            migration_type=MigrationType.ALTER.name,
                            duration=(datetime.utcnow() - start_time).total_seconds(),
                            timestamp=datetime.utcnow().isoformat(),
                        )
                    )

                except sqlite3.Error as e:
                    error = f"Migration failed: {str(e)}"
                    logger.error(error, exc_info=True)
                    results.append(
                        MigrationResult(
                            success=False,
                            error=str(e),
                            migration_type=MigrationType.ALTER.name,
                            duration=(datetime.utcnow() - start_time).total_seconds(),
                            timestamp=datetime.utcnow().isoformat(),
                        )
                    )
                    raise DatabaseError(
                        error,
                        context=ErrorContext(
                            "SchemaManager",
                            "apply_migrations",
                            {
                                "current_version": current_version,
                                "migration": migration,
                                "results": results,
                            },
                            ErrorSeverity.CRITICAL,
                        ),
                    )

    def _get_migrations(self, current_version: int) -> List[str]:
        """
        Get list of migrations to apply.

        Args:
            current_version: Current schema version

        Returns:
            List of migration scripts
        """
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
                    bitrate INTEGER,
                    error_count INTEGER DEFAULT 0,
                    last_error TEXT,
                    last_accessed TIMESTAMP,
                    metadata TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_guild_channel 
                ON archived_videos(guild_id, channel_id);
                
                CREATE INDEX IF NOT EXISTS idx_archived_at 
                ON archived_videos(archived_at);
                
                CREATE INDEX IF NOT EXISTS idx_last_accessed
                ON archived_videos(last_accessed);
            """
            )

        # Add more migrations here as schema evolves
        # if current_version < 2:
        #     migrations.append(...)

        return migrations

    def get_status(self) -> SchemaStatus:
        """
        Get current schema status.

        Returns:
            Schema status information
        """
        return SchemaStatus(
            state=self.state.name,
            current_version=self._get_schema_version(),
            target_version=self.SCHEMA_VERSION,
            last_migration=self.last_migration,
            error=self.last_error,
            initialized=self.state == SchemaState.READY,
        )

    def get_version_info(self) -> SchemaVersion:
        """
        Get detailed version information.

        Returns:
            Schema version information

        Raises:
            DatabaseError: If version query fails
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT version, last_updated, migrations_applied
                    FROM schema_version LIMIT 1
                    """
                )
                result = cursor.fetchone()
                if result:
                    return SchemaVersion(
                        version=result[0],
                        last_updated=result[1],
                        migrations_applied=result[2].split(",") if result[2] else [],
                    )
                return SchemaVersion(version=0, last_updated="", migrations_applied=[])

        except sqlite3.Error as e:
            error = f"Failed to get version info: {str(e)}"
            logger.error(error, exc_info=True)
            raise DatabaseError(
                error,
                context=ErrorContext(
                    "SchemaManager", "get_version_info", None, ErrorSeverity.HIGH
                ),
            )
