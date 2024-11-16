"""Utility functions and classes for VideoArchiver"""

from .file_ops import (
    cleanup_downloads,
    ensure_directory,
    get_file_size,
    is_valid_path,
    safe_delete
)
from .file_deletion import FileDeleter
from .directory_manager import DirectoryManager
from .permission_manager import PermissionManager
from .download_manager import DownloadManager
from .compression_manager import CompressionManager
from .progress_tracker import ProgressTracker
from .path_manager import PathManager
from .exceptions import (
    FileOperationError,
    DirectoryError,
    PermissionError,
    DownloadError,
    CompressionError,
    TrackingError,
    PathError
)

__all__ = [
    # File Operations
    'cleanup_downloads',
    'ensure_directory',
    'get_file_size',
    'is_valid_path',
    'safe_delete',
    
    # Managers
    'FileDeleter',
    'DirectoryManager',
    'PermissionManager',
    'DownloadManager',
    'CompressionManager',
    'ProgressTracker',
    'PathManager',
    
    # Exceptions
    'FileOperationError',
    'DirectoryError',
    'PermissionError',
    'DownloadError',
    'CompressionError',
    'TrackingError',
    'PathError'
]

# Initialize shared instances for module-level access
directory_manager = DirectoryManager()
permission_manager = PermissionManager()
download_manager = DownloadManager()
compression_manager = CompressionManager()
progress_tracker = ProgressTracker()
path_manager = PathManager()
