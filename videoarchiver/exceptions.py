"""Base exceptions for VideoArchiver"""

from .utils.exceptions import (
    VideoArchiverError,
    ConfigurationError,
    VideoVerificationError,
    QueueError,
    FileCleanupError,
)

# Re-export base exceptions
__all__ = [
    'VideoArchiverError',
    'ConfigurationError',
    'VideoVerificationError',
    'QueueError',
    'FileCleanupError',
    'UpdateError',
    'ProcessingError',
    'ConfigError',
]

# Alias exceptions for backward compatibility
ProcessingError = VideoArchiverError
ConfigError = ConfigurationError
UpdateError = VideoVerificationError
