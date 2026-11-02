"""Utility functions and classes for VideoArchiver"""

from typing import Dict, Optional, Any, Union, List

from .file_ops import (
    cleanup_downloads,
    ensure_directory,
)
from .file_deletion import SecureFileDeleter
from .directory_manager import DirectoryManager
from .permission_manager import PermissionManager
from .download_manager import DownloadManager
from .compression_manager import CompressionManager
from .progress_tracker import (
    ProgressTracker,
    ProgressStatus,
)
from .path_manager import PathManager
from .exceptions import (
    # Base exception
    VideoArchiverError,
    ErrorSeverity,
    ErrorContext,
    
    # File operations
    FileOperationError,
    PermissionError,
    FileCleanupError,
    
    # Video operations
    VideoDownloadError,
    VideoProcessingError,
    VideoVerificationError,
    VideoUploadError,
    VideoCleanupError,
    
    # Resource management
    ResourceError,
    ResourceExhaustedError,
    
    # Network and API
    NetworkError,
    DiscordAPIError,
    
    # Component operations
    ComponentError,
    ConfigurationError,
    DatabaseError,
    FFmpegError,
    
    # Queue operations
    QueueError,
    QueueHandlerError,
    QueueProcessorError,
    
    # Processing operations
    ProcessingError,
    ProcessorError,
    ValidationError,
    DisplayError,
    URLExtractionError,
    MessageHandlerError,
    
    # Cleanup operations
    CleanupError,
    
    # Health monitoring
    HealthCheckError,
    
    # Command and Event operations
    CommandError,
    EventError,
    
    # Cog operations
    CogError,
    
    # Progress tracking
    TrackingError
)

# ProgressTracker is a singleton, so this is the same instance processor uses
progress_tracker = ProgressTracker()

__all__ = [
    # File Operations
    'cleanup_downloads',
    'ensure_directory',
    
    # Managers
    'SecureFileDeleter',
    'DirectoryManager',
    'PermissionManager',
    'DownloadManager',
    'CompressionManager',
    'ProgressTracker',
    'PathManager',
    
    # Progress Tracking Types
    'ProgressStatus',
    
    # Base Exceptions
    'VideoArchiverError',
    'ErrorSeverity',
    'ErrorContext',
    
    # File Operation Exceptions
    'FileOperationError',
    'PermissionError',
    'FileCleanupError',
    
    # Video Operation Exceptions
    'VideoDownloadError',
    'VideoProcessingError',
    'VideoVerificationError',
    'VideoUploadError',
    'VideoCleanupError',
    
    # Resource Exceptions
    'ResourceError',
    'ResourceExhaustedError',
    
    # Network and API Exceptions
    'NetworkError',
    'DiscordAPIError',
    
    # Component Exceptions
    'ComponentError',
    'ConfigurationError',
    'DatabaseError',
    'FFmpegError',
    
    # Queue Exceptions
    'QueueError',
    'QueueHandlerError',
    'QueueProcessorError',
    
    # Processing Exceptions
    'ProcessingError',
    'ProcessorError',
    'ValidationError',
    'DisplayError',
    'URLExtractionError',
    'MessageHandlerError',
    
    # Cleanup Exceptions
    'CleanupError',
    
    # Health Monitoring Exceptions
    'HealthCheckError',
    
    # Command and Event Exceptions
    'CommandError',
    'EventError',
    
    # Cog Exceptions
    'CogError',
    
    # Progress Tracking Exceptions
    'TrackingError',
    
    # Helper Functions
    'get_download_progress',
    'get_compression_progress',
    'get_active_downloads',
    'get_active_compressions'
]

# Version information
__version__ = "1.0.0"
__author__ = "VideoArchiver Team"
__description__ = "Utility functions and classes for VideoArchiver"

# Progress tracking helper functions
def get_download_progress(url: Optional[str] = None) -> Dict[str, Any]:
    """
    Get progress information for a download.
    
    Args:
        url: Optional URL to get progress for. If None, returns all progress.
        
    Returns:
        If url is provided, returns progress for that URL or None if not found.
        If url is None, returns dictionary of all download progress.
        
    Raises:
        TrackingError: If there's an error getting progress information
    """
    try:
        return progress_tracker.get_download_progress(url)
    except Exception as e:
        raise TrackingError(f"Failed to get download progress: {str(e)}")

def get_compression_progress(input_file: Optional[str] = None) -> Dict[str, Any]:
    """
    Get progress information for a compression operation.
    
    Args:
        input_file: Optional file to get progress for. If None, returns all progress.
        
    Returns:
        If input_file is provided, returns progress for that file or None if not found.
        If input_file is None, returns dictionary of all compression progress.
        
    Raises:
        TrackingError: If there's an error getting progress information
    """
    try:
        return progress_tracker.get_compression_progress(input_file)
    except Exception as e:
        raise TrackingError(f"Failed to get compression progress: {str(e)}")

def get_active_downloads() -> Dict[str, Any]:
    """
    Get all active downloads.
    
    Returns:
        Dictionary mapping URLs to their download progress information
        
    Raises:
        TrackingError: If there's an error getting active downloads
    """
    try:
        return {k: v for k, v in progress_tracker.get_download_progress().items() if v.get("active")}
    except Exception as e:
        raise TrackingError(f"Failed to get active downloads: {str(e)}")

def get_active_compressions() -> Dict[str, Any]:
    """
    Get all active compression operations.
    
    Returns:
        Dictionary mapping file paths to their compression progress information
        
    Raises:
        TrackingError: If there's an error getting active compressions
    """
    try:
        return {k: v for k, v in progress_tracker.get_compression_progress().items() if v.get("active")}
    except Exception as e:
        raise TrackingError(f"Failed to get active compressions: {str(e)}")

# Error handling helper functions
def create_error_context(
    component: str,
    operation: str,
    details: Optional[Dict[str, Any]] = None,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
) -> ErrorContext:
    """
    Create an error context object.
    
    Args:
        component: Component where error occurred
        operation: Operation that failed
        details: Optional error details
        severity: Error severity level
        
    Returns:
        ErrorContext object
    """
    return ErrorContext(component, operation, details, severity)
