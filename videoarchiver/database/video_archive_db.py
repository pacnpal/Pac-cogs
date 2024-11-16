"""Database management for archived videos"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from .schema_manager import SchemaManager
from .query_manager import QueryManager
from .connection_manager import ConnectionManager

logger = logging.getLogger("VideoArchiverDB")

class VideoArchiveDB:
    """Manages the SQLite database for archived videos"""
    
    def __init__(self, data_path: Path):
        """Initialize the database and its components
        
        Args:
            data_path: Path to the data directory
        """
        # Set up database path
        self.db_path = data_path / "archived_videos.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize managers
        self.connection_manager = ConnectionManager(self.db_path)
        self.schema_manager = SchemaManager(self.db_path)
        self.query_manager = QueryManager(self.connection_manager)
        
        # Initialize database schema
        self.schema_manager.initialize_schema()
        logger.info("Video archive database initialized successfully")

    async def add_archived_video(
        self,
        original_url: str,
        discord_url: str,
        message_id: int,
        channel_id: int,
        guild_id: int,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Add a newly archived video to the database"""
        return await self.query_manager.add_archived_video(
            original_url,
            discord_url,
            message_id,
            channel_id,
            guild_id,
            metadata
        )

    async def get_archived_video(self, url: str) -> Optional[Dict[str, Any]]:
        """Get archived video information by original URL"""
        return await self.query_manager.get_archived_video(url)

    async def is_url_archived(self, url: str) -> bool:
        """Check if a URL has already been archived"""
        return await self.query_manager.is_url_archived(url)

    async def get_guild_stats(self, guild_id: int) -> Dict[str, Any]:
        """Get archiving statistics for a guild"""
        return await self.query_manager.get_guild_stats(guild_id)

    async def get_channel_videos(
        self,
        channel_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get archived videos for a channel"""
        return await self.query_manager.get_channel_videos(
            channel_id,
            limit,
            offset
        )

    async def cleanup_old_records(self, days: int) -> int:
        """Clean up records older than specified days"""
        return await self.query_manager.cleanup_old_records(days)

    def close(self) -> None:
        """Close all database connections"""
        try:
            self.connection_manager.close_all()
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error closing database connections: {e}")

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        self.close()
