"""Module for managing database queries"""

import logging
import sqlite3
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime

logger = logging.getLogger("DBQueryManager")

class QueryManager:
    """Manages database queries and operations"""

    def __init__(self, connection_manager):
        self.connection_manager = connection_manager

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
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Prepare query and parameters
                query = """
                    INSERT OR REPLACE INTO archived_videos 
                    (original_url, discord_url, message_id, channel_id, guild_id,
                     file_size, duration, format, resolution, bitrate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                
                # Extract metadata values with defaults
                metadata = metadata or {}
                params = (
                    original_url,
                    discord_url,
                    message_id,
                    channel_id,
                    guild_id,
                    metadata.get('file_size'),
                    metadata.get('duration'),
                    metadata.get('format'),
                    metadata.get('resolution'),
                    metadata.get('bitrate')
                )
                
                cursor.execute(query, params)
                conn.commit()
                return True

        except sqlite3.Error as e:
            logger.error(f"Error adding archived video: {e}")
            return False

    async def get_archived_video(
        self,
        url: str
    ) -> Optional[Dict[str, Any]]:
        """Get archived video information by original URL"""
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT discord_url, message_id, channel_id, guild_id,
                           file_size, duration, format, resolution, bitrate,
                           archived_at
                    FROM archived_videos
                    WHERE original_url = ?
                """, (url,))
                
                result = cursor.fetchone()
                if not result:
                    return None
                    
                return {
                    'discord_url': result[0],
                    'message_id': result[1],
                    'channel_id': result[2],
                    'guild_id': result[3],
                    'file_size': result[4],
                    'duration': result[5],
                    'format': result[6],
                    'resolution': result[7],
                    'bitrate': result[8],
                    'archived_at': result[9]
                }

        except sqlite3.Error as e:
            logger.error(f"Error retrieving archived video: {e}")
            return None

    async def is_url_archived(self, url: str) -> bool:
        """Check if a URL has already been archived"""
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM archived_videos WHERE original_url = ?",
                    (url,)
                )
                return cursor.fetchone() is not None

        except sqlite3.Error as e:
            logger.error(f"Error checking archived status: {e}")
            return False

    async def get_guild_stats(self, guild_id: int) -> Dict[str, Any]:
        """Get archiving statistics for a guild"""
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_videos,
                        SUM(file_size) as total_size,
                        AVG(duration) as avg_duration,
                        MAX(archived_at) as last_archived
                    FROM archived_videos
                    WHERE guild_id = ?
                """, (guild_id,))
                
                result = cursor.fetchone()
                return {
                    'total_videos': result[0],
                    'total_size': result[1] or 0,
                    'avg_duration': result[2] or 0,
                    'last_archived': result[3]
                }

        except sqlite3.Error as e:
            logger.error(f"Error getting guild stats: {e}")
            return {
                'total_videos': 0,
                'total_size': 0,
                'avg_duration': 0,
                'last_archived': None
            }

    async def get_channel_videos(
        self,
        channel_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get archived videos for a channel"""
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT original_url, discord_url, message_id,
                           file_size, duration, format, resolution,
                           archived_at
                    FROM archived_videos
                    WHERE channel_id = ?
                    ORDER BY archived_at DESC
                    LIMIT ? OFFSET ?
                """, (channel_id, limit, offset))
                
                results = cursor.fetchall()
                return [{
                    'original_url': row[0],
                    'discord_url': row[1],
                    'message_id': row[2],
                    'file_size': row[3],
                    'duration': row[4],
                    'format': row[5],
                    'resolution': row[6],
                    'archived_at': row[7]
                } for row in results]

        except sqlite3.Error as e:
            logger.error(f"Error getting channel videos: {e}")
            return []

    async def cleanup_old_records(self, days: int) -> int:
        """Clean up records older than specified days"""
        try:
            with self.connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM archived_videos
                    WHERE archived_at < datetime('now', ? || ' days')
                """, (-days,))
                
                deleted = cursor.rowcount
                conn.commit()
                return deleted

        except sqlite3.Error as e:
            logger.error(f"Error cleaning up old records: {e}")
            return 0
