"""FFmpeg-related exceptions"""

class FFmpegError(Exception):
    """Base exception for FFmpeg-related errors"""
    pass

class GPUError(FFmpegError):
    """Raised when GPU operations fail"""
    pass

class DownloadError(FFmpegError):
    """Raised when FFmpeg download fails"""
    pass
