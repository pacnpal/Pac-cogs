"""Database management for archived videos"""
import sqlite3
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("VideoArchiverDB")

class VideoArchiveDB:
    """Manages the SQLite database for archived videos"""
    
    def __init__(self, data_path: Path):
        """Initialize the database connection"""
        self.db_path = data_path / "archived_videos.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize the database schema"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS archived_videos (
                        original_url TEXT PRIMARY KEY,
                        discord_url TEXT NOT NULL,
                        message_id INTEGER NOT NULL,
                        channel_id INTEGER NOT NULL,
                        guild_id INTEGER NOT NULL,
                        archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise

    def add_archived_video(self, original_url: str, discord_url: str, message_id: int, channel_id: int, guild_id: int) -> bool:
        """Add a newly archived video to the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO archived_videos 
                    (original_url, discord_url, message_id, channel_id, guild_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (original_url, discord_url, message_id, channel_id, guild_id))
                conn.commit()
                return True
        except sqlite3.Error as e:
            logger.error(f"Error adding archived video: {e}")
            return False

    def get_archived_video(self, url: str) -> Optional[Tuple[str, int, int, int]]:
        """Get archived video information by original URL"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT discord_url, message_id, channel_id, guild_id
                    FROM archived_videos
                    WHERE original_url = ?
                """, (url,))
                result = cursor.fetchone()
                return result if result else None
        except sqlite3.Error as e:
            logger.error(f"Error retrieving archived video: {e}")
            return None

    def is_url_archived(self, url: str) -> bool:
        """Check if a URL has already been archived"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM archived_videos WHERE original_url = ?", (url,))
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Error checking archived status: {e}")
            return False
