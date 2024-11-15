"""Custom exceptions for VideoArchiver"""

class VideoArchiverError(Exception):
    """Base exception for VideoArchiver errors"""
    pass

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
    pass

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
    def __init__(self, message: str, status_code: int = None):
        self.status_code = status_code
        super().__init__(f"Discord API Error: {message} (Status: {status_code if status_code else 'Unknown'})")

class ResourceExhaustedError(VideoArchiverError):
    """Error when system resources are exhausted"""
    def __init__(self, message: str, resource_type: str = None):
        self.resource_type = resource_type
        super().__init__(f"Resource exhausted: {message} (Type: {resource_type if resource_type else 'Unknown'})")

class ProcessingError(VideoArchiverError):
    """Error during video processing"""
    pass

class CleanupError(VideoArchiverError):
    """Error during cleanup operations"""
    pass

class FileOperationError(VideoArchiverError):
    """Error during file operations"""
    pass
