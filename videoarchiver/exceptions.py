"""Base exceptions for VideoArchiver"""

from .utils.exceptions import (
    VideoArchiverError,
    ConfigurationError,
    VideoVerificationError,
    QueueError,
    FileCleanupError,
    ResourceExhaustedError,
    ProcessingError,
    CleanupError,
    FileOperationError,
    VideoDownloadError,
    VideoProcessingError,
    VideoUploadError,
    VideoCleanupError,
    PermissionError,
    NetworkError,
    ResourceError,
    ComponentError,
    DiscordAPIError,
)

# Re-export all exceptions
__all__ = [
    "VideoArchiverError",
    "ConfigurationError",
    "VideoVerificationError",
    "QueueError",
    "FileCleanupError",
    "ResourceExhaustedError",
    "ProcessingError",
    "CleanupError",
    "FileOperationError",
    "VideoDownloadError",
    "VideoProcessingError",
    "VideoUploadError",
    "VideoCleanupError",
    "PermissionError",
    "NetworkError",
    "ResourceError",
    "ComponentError",
    "DiscordAPIError",
]

# Alias exceptions for backward compatibility
ConfigError = ConfigurationError
UpdateError = VideoVerificationError
