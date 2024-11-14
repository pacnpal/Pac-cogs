"""FFmpeg management package"""

from .exceptions import FFmpegError, GPUError, DownloadError

# Import the manager class directly in the modules that need it
# to avoid circular imports
__all__ = ['FFmpegError', 'GPUError', 'DownloadError']
