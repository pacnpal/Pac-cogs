"""FFmpeg management package"""

from videoarchiver.ffmpeg.exceptions import FFmpegError, GPUError, DownloadError
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager

__all__ = ['FFmpegManager', 'FFmpegError', 'GPUError', 'DownloadError']
