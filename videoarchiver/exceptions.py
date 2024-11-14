"""Custom exceptions for the VideoArchiver cog"""

class ProcessingError(Exception):
    """Base exception for video processing errors"""
    def __init__(self, message: str, details: str = None):
        self.message = message
        self.details = details
        super().__init__(self.message)

class DiscordAPIError(ProcessingError):
    """Raised when Discord API operations fail"""
    pass

class UpdateError(ProcessingError):
    """Raised when update operations fail"""
    pass

class DownloadError(ProcessingError):
    """Raised when video download operations fail"""
    pass

class QueueError(ProcessingError):
    """Raised when queue operations fail"""
    pass

class ConfigError(ProcessingError):
    """Raised when configuration operations fail"""
    pass

class FileOperationError(ProcessingError):
    """Raised when file operations fail"""
    pass

class VideoValidationError(ProcessingError):
    """Raised when video validation fails"""
    pass

class PermissionError(ProcessingError):
    """Raised when permission checks fail"""
    pass

class ResourceExhaustedError(ProcessingError):
    """Raised when system resources are exhausted"""
    pass

class NetworkError(ProcessingError):
    """Raised when network operations fail"""
    pass

class FFmpegError(ProcessingError):
    """Raised when FFmpeg operations fail"""
    pass

class CleanupError(ProcessingError):
    """Raised when cleanup operations fail"""
    pass

class URLExtractionError(ProcessingError):
    """Raised when URL extraction fails"""
    pass

class MessageFormatError(ProcessingError):
    """Raised when message formatting fails"""
    pass
