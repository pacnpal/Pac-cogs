"""Custom exceptions for VideoArchiver"""

from typing import Optional, Dict, Any
from enum import Enum, auto

class ErrorSeverity(Enum):
    """Severity levels for errors"""
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()

class ErrorContext:
    """Context information for errors"""
    def __init__(
        self,
        component: str,
        operation: str,
        details: Optional[Dict[str, Any]] = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM
    ) -> None:
        self.component = component
        self.operation = operation
        self.details = details or {}
        self.severity = severity

    def __str__(self) -> str:
        return (
            f"[{self.severity.name}] {self.component}.{self.operation}: "
            f"{', '.join(f'{k}={v}' for k, v in self.details.items())}"
        )

class VideoArchiverError(Exception):
    """Base exception for VideoArchiver errors"""
    def __init__(
        self,
        message: str,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.context = context
        super().__init__(f"{context}: {message}" if context else message)

class VideoDownloadError(VideoArchiverError):
    """Error downloading video"""
    pass

class VideoProcessingError(VideoArchiverError):
    """Error processing video"""
    pass

class VideoVerificationError(VideoArchiverError):
    """Error verifying video"""
    pass

class VideoUploadError(VideoArchiverError):
    """Error uploading video"""
    pass

class VideoCleanupError(VideoArchiverError):
    """Error cleaning up video files"""
    pass

class FileCleanupError(VideoArchiverError):
    """Error cleaning up files"""
    pass

class ConfigurationError(VideoArchiverError):
    """Error in configuration"""
    pass

class PermissionError(VideoArchiverError):
    """Error with file permissions"""
    pass

class NetworkError(VideoArchiverError):
    """Error with network operations"""
    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        status_code: Optional[int] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.url = url
        self.status_code = status_code
        details = f" (URL: {url}" + (f", Status: {status_code})" if status_code else ")")
        super().__init__(message + details, context)

class ResourceError(VideoArchiverError):
    """Error with system resources"""
    pass

class QueueError(VideoArchiverError):
    """Error with queue operations"""
    pass

class ComponentError(VideoArchiverError):
    """Error with component initialization or cleanup"""
    pass

class DiscordAPIError(VideoArchiverError):
    """Error with Discord API operations"""
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.status_code = status_code
        details = f" (Status: {status_code})" if status_code else ""
        super().__init__(f"Discord API Error: {message}{details}", context)

class ResourceExhaustedError(VideoArchiverError):
    """Error when system resources are exhausted"""
    def __init__(
        self,
        message: str,
        resource_type: Optional[str] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.resource_type = resource_type
        details = f" (Type: {resource_type})" if resource_type else ""
        super().__init__(f"Resource exhausted: {message}{details}", context)

class ProcessingError(VideoArchiverError):
    """Error during video processing"""
    pass

class CleanupError(VideoArchiverError):
    """Error during cleanup operations"""
    pass

class FileOperationError(VideoArchiverError):
    """Error during file operations"""
    def __init__(
        self,
        message: str,
        path: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.path = path
        self.operation = operation
        details = []
        if path:
            details.append(f"Path: {path}")
        if operation:
            details.append(f"Operation: {operation}")
        details_str = f" ({', '.join(details)})" if details else ""
        super().__init__(f"File operation error: {message}{details_str}", context)

# New exceptions for processor components
class ProcessorError(VideoArchiverError):
    """Error in video processor operations"""
    pass

class ValidationError(VideoArchiverError):
    """Error in message or content validation"""
    pass

class DisplayError(VideoArchiverError):
    """Error in status display operations"""
    pass

class URLExtractionError(VideoArchiverError):
    """Error extracting URLs from content"""
    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.url = url
        details = f" (URL: {url})" if url else ""
        super().__init__(f"URL extraction error: {message}{details}", context)

class MessageHandlerError(VideoArchiverError):
    """Error in message handling operations"""
    def __init__(
        self,
        message: str,
        message_id: Optional[int] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.message_id = message_id
        details = f" (Message ID: {message_id})" if message_id else ""
        super().__init__(f"Message handler error: {message}{details}", context)

class QueueHandlerError(VideoArchiverError):
    """Error in queue handling operations"""
    pass

class QueueProcessorError(VideoArchiverError):
    """Error in queue processing operations"""
    pass

class FFmpegError(VideoArchiverError):
    """Error in FFmpeg operations"""
    def __init__(
        self,
        message: str,
        command: Optional[str] = None,
        exit_code: Optional[int] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.command = command
        self.exit_code = exit_code
        details = []
        if command:
            details.append(f"Command: {command}")
        if exit_code is not None:
            details.append(f"Exit Code: {exit_code}")
        details_str = f" ({', '.join(details)})" if details else ""
        super().__init__(f"FFmpeg error: {message}{details_str}", context)

class DatabaseError(VideoArchiverError):
    """Error in database operations"""
    def __init__(
        self,
        message: str,
        query: Optional[str] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.query = query
        details = f" (Query: {query})" if query else ""
        super().__init__(f"Database error: {message}{details}", context)

class HealthCheckError(VideoArchiverError):
    """Error in health check operations"""
    def __init__(
        self,
        message: str,
        component: Optional[str] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.component = component
        details = f" (Component: {component})" if component else ""
        super().__init__(f"Health check error: {message}{details}", context)

class TrackingError(VideoArchiverError):
    """Error in progress tracking operations"""
    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        item_id: Optional[str] = None,
        context: Optional[ErrorContext] = None
    ) -> None:
        self.operation = operation
        self.item_id = item_id
        details = []
        if operation:
            details.append(f"Operation: {operation}")
        if item_id:
            details.append(f"Item ID: {item_id}")
        details_str = f" ({', '.join(details)})" if details else ""
        super().__init__(f"Progress tracking error: {message}{details_str}", context)
