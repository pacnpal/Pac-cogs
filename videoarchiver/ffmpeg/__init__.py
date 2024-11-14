"""FFmpeg management package"""

from ffmpeg.exceptions import FFmpegError, GPUError, DownloadError
from ffmpeg.ffmpeg_manager import FFmpegManager

__all__ = ['FFmpegManager', 'FFmpegError', 'GPUError', 'DownloadError']
