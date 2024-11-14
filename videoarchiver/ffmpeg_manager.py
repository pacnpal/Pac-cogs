"""FFmpeg management module"""

# Import directly from the local ffmpeg package
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager
from videoarchiver.ffmpeg.exceptions import FFmpegError, GPUError, DownloadError

__all__ = ['FFmpegManager', 'FFmpegError', 'GPUError', 'DownloadError']
