"""Base exceptions for VideoArchiver"""

from .utils.exceptions import (
    VideoArchiverError,
    ConfigurationError,
    VideoVerificationError,
    QueueError,
    FileCleanupError,
    DiscordAPIError,
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
    'DiscordAPIError',
]

# Alias exceptions for backward compatibility
ProcessingError = VideoArchiverError
ConfigError = ConfigurationError
UpdateError = VideoVerificationError
