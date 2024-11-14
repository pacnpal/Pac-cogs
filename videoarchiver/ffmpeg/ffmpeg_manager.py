"""Main FFmpeg management module"""

import os
import platform
import multiprocessing
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from .exceptions import FFmpegError
from .gpu_detector import GPUDetector
from .video_analyzer import VideoAnalyzer
from .encoder_params import EncoderParams
from .ffmpeg_downloader import FFmpegDownloader

logger = logging.getLogger("VideoArchiver")

class FFmpegManager:
    def __init__(self):
        """Initialize FFmpeg manager"""
        # Set up base directory in /tmp for Docker compatibility
        self.base_dir = Path("/tmp/ffmpeg")
        
        # Initialize downloader
        self.downloader = FFmpegDownloader(
            system=platform.system(),
            machine=platform.machine(),
            base_dir=self.base_dir
        )
        
        # Get or download FFmpeg
        self.ffmpeg_path = self._initialize_ffmpeg()
        
        # Initialize components
        self.gpu_detector = GPUDetector(self.ffmpeg_path)
        self.video_analyzer = VideoAnalyzer(self.ffmpeg_path)
        self._gpu_info = self.gpu_detector.detect_gpu()
        self._cpu_cores = multiprocessing.cpu_count()
        
        # Initialize encoder params
        self.encoder_params = EncoderParams(self._cpu_cores, self._gpu_info)

    def _initialize_ffmpeg(self) -> Path:
        """Initialize FFmpeg binary"""
        # Verify existing FFmpeg if it exists
        if self.downloader.ffmpeg_path.exists() and self.downloader.verify():
            logger.info(f"Using existing FFmpeg: {self.downloader.ffmpeg_path}")
            return self.downloader.ffmpeg_path

        # Download and verify FFmpeg
        logger.info("Downloading FFmpeg...")
        try:
            ffmpeg_path = self.downloader.download()
            if not self.downloader.verify():
                raise FFmpegError("Downloaded FFmpeg binary is not functional")
            return ffmpeg_path
        except Exception as e:
            logger.error(f"Failed to initialize FFmpeg: {e}")
            raise FFmpegError(f"Failed to initialize FFmpeg: {e}")

    def analyze_video(self, input_path: str) -> Dict[str, Any]:
        """Analyze video content for optimal encoding settings"""
        return self.video_analyzer.analyze_video(input_path)

    def get_compression_params(self, input_path: str, target_size_mb: int) -> Dict[str, str]:
        """Get optimal compression parameters for the given input file"""
        # Analyze video first
        video_info = self.analyze_video(input_path)
        # Get encoding parameters
        return self.encoder_params.get_params(video_info, target_size_mb * 1024 * 1024)

    def get_ffmpeg_path(self) -> str:
        """Get path to FFmpeg binary"""
        if not self.ffmpeg_path.exists():
            raise FFmpegError("FFmpeg is not available")
        return str(self.ffmpeg_path)

    def force_download(self) -> bool:
        """Force re-download of FFmpeg binary"""
        try:
            logger.info("Force downloading FFmpeg...")
            self.ffmpeg_path = self.downloader.download()
            return self.downloader.verify()
        except Exception as e:
            logger.error(f"Failed to force download FFmpeg: {e}")
            return False

    @property
    def gpu_info(self) -> Dict[str, bool]:
        """Get GPU information"""
        return self._gpu_info.copy()

    @property
    def cpu_cores(self) -> int:
        """Get number of CPU cores"""
        return self._cpu_cores
