"""FFmpeg management module"""

# Import from the local ffmpeg package
from ffmpeg.ffmpeg_manager import FFmpegManager
from ffmpeg.exceptions import FFmpegError, GPUError, DownloadError

__all__ = ['FFmpegManager', 'FFmpegError', 'GPUError', 'DownloadError']
