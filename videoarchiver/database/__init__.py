"""Database management package for video archiving"""

try:
    # Try relative imports first
    from .connection_manager import DatabaseConnectionManager
    from .query_manager import DatabaseQueryManager
    from .schema_manager import DatabaseSchemaManager
    from .video_archive_db import VideoArchiveDB
except ImportError:
    # Fall back to absolute imports if relative imports fail
    from videoarchiver.database.connection_manager import DatabaseConnectionManager
    from videoarchiver.database.query_manager import DatabaseQueryManager
    from videoarchiver.database.schema_manager import DatabaseSchemaManager
    from videoarchiver.database.video_archive_db import VideoArchiveDB

__all__ = [
    'DatabaseConnectionManager',
    'DatabaseQueryManager',
    'DatabaseSchemaManager',
    'VideoArchiveDB'
]
