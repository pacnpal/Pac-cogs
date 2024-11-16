"""Main FFmpeg management module"""

import logging
import platform
import multiprocessing
from pathlib import Path
from typing import Dict, Any, Optional

from .exceptions import (
    FFmpegError,
    AnalysisError,
    FFmpegNotFoundError
)
from .gpu_detector import GPUDetector
from .video_analyzer import VideoAnalyzer
from .encoder_params import EncoderParams
from .process_manager import ProcessManager
from .verification_manager import VerificationManager
from .binary_manager import BinaryManager

logger = logging.getLogger("VideoArchiver")

class FFmpegManager:
    """Manages FFmpeg operations and lifecycle"""

    def __init__(self):
        """Initialize FFmpeg manager"""
        # Set up base directory in videoarchiver/bin
        module_dir = Path(__file__).parent.parent
        self.base_dir = module_dir / "bin"
        logger.info(f"FFmpeg base directory: {self.base_dir}")
        
        # Initialize managers
        self.process_manager = ProcessManager()
        self.verification_manager = VerificationManager(self.process_manager)
        self.binary_manager = BinaryManager(
            base_dir=self.base_dir,
            system=platform.system(),
            machine=platform.machine(),
            verification_manager=self.verification_manager
        )
        
        # Initialize components
        self.gpu_detector = GPUDetector(self.get_ffmpeg_path)
        self.video_analyzer = VideoAnalyzer(self.get_ffmpeg_path)
        self._gpu_info = self.gpu_detector.detect_gpu()
        self._cpu_cores = multiprocessing.cpu_count()
        
        # Initialize encoder params
        self.encoder_params = EncoderParams(self._cpu_cores, self._gpu_info)

        # Initialize binaries
        binaries = self.binary_manager.initialize_binaries(self._gpu_info)
        logger.info(f"Using FFmpeg from: {binaries['ffmpeg']}")
        logger.info(f"Using FFprobe from: {binaries['ffprobe']}")
        logger.info("FFmpeg manager initialized successfully")

    def kill_all_processes(self) -> None:
        """Kill all active FFmpeg processes"""
        self.process_manager.kill_all_processes()

    def analyze_video(self, input_path: str) -> Dict[str, Any]:
        """Analyze video content for optimal encoding settings"""
        try:
            if not input_path or not Path(input_path).exists():
                raise FileNotFoundError(f"Input file not found: {input_path}")
            return self.video_analyzer.analyze_video(input_path)
        except Exception as e:
            logger.error(f"Video analysis failed: {e}")
            if isinstance(e, FileNotFoundError):
                raise
            raise AnalysisError(f"Failed to analyze video: {e}")

    def get_compression_params(self, input_path: str, target_size_mb: int) -> Dict[str, str]:
        """Get optimal compression parameters for the given input file"""
        try:
            # Analyze video first
            video_info = self.analyze_video(input_path)
            if not video_info:
                raise AnalysisError("Failed to analyze video")
                
            # Convert target size to bytes
            target_size_bytes = target_size_mb * 1024 * 1024
            
            # Get encoding parameters
            params = self.encoder_params.get_params(video_info, target_size_bytes)
            logger.info(f"Generated compression parameters: {params}")
            return params
            
        except Exception as e:
            logger.error(f"Failed to get compression parameters: {e}")
            if isinstance(e, AnalysisError):
                raise
            # Return safe default parameters
            return {
                "c:v": "libx264",
                "preset": "medium",
                "crf": "23",
                "c:a": "aac",
                "b:a": "128k"
            }

    def get_ffmpeg_path(self) -> str:
        """Get path to FFmpeg binary"""
        return self.binary_manager.get_ffmpeg_path()

    def get_ffprobe_path(self) -> str:
        """Get path to FFprobe binary"""
        return self.binary_manager.get_ffprobe_path()

    def force_download(self) -> bool:
        """Force re-download of FFmpeg binary"""
        return self.binary_manager.force_download(self._gpu_info)

    @property
    def gpu_info(self) -> Dict[str, bool]:
        """Get GPU information"""
        return self._gpu_info.copy()

    @property
    def cpu_cores(self) -> int:
        """Get number of CPU cores"""
        return self._cpu_cores
