"""Main FFmpeg management module"""

import os
import platform
import multiprocessing
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from videoarchiver.ffmpeg.exceptions import FFmpegError
from videoarchiver.ffmpeg.gpu_detector import GPUDetector
from videoarchiver.ffmpeg.video_analyzer import VideoAnalyzer
from videoarchiver.ffmpeg.encoder_params import EncoderParams
from videoarchiver.ffmpeg.ffmpeg_downloader import FFmpegDownloader

logger = logging.getLogger("VideoArchiver")

class FFmpegManager:
    def __init__(self):
        """Initialize FFmpeg manager"""
        # Set up base directory in videoarchiver/bin
        module_dir = Path(__file__).parent.parent
        self.base_dir = module_dir / "bin"
        logger.info(f"FFmpeg base directory: {self.base_dir}")
        
        # Initialize downloader
        self.downloader = FFmpegDownloader(
            system=platform.system(),
            machine=platform.machine(),
            base_dir=self.base_dir
        )
        
        # Get or download FFmpeg
        self.ffmpeg_path = self._initialize_ffmpeg()
        logger.info(f"Using FFmpeg from: {self.ffmpeg_path}")
        
        # Initialize components
        self.gpu_detector = GPUDetector(self.ffmpeg_path)
        self.video_analyzer = VideoAnalyzer(self.ffmpeg_path)
        self._gpu_info = self.gpu_detector.detect_gpu()
        self._cpu_cores = multiprocessing.cpu_count()
        
        # Initialize encoder params
        self.encoder_params = EncoderParams(self._cpu_cores, self._gpu_info)
        
        # Verify FFmpeg functionality
        self._verify_ffmpeg()
        logger.info("FFmpeg manager initialized successfully")

    def _initialize_ffmpeg(self) -> Path:
        """Initialize FFmpeg binary with proper error handling"""
        try:
            # Verify existing FFmpeg if it exists
            if self.downloader.ffmpeg_path.exists():
                logger.info(f"Found existing FFmpeg: {self.downloader.ffmpeg_path}")
                if self.downloader.verify():
                    return self.downloader.ffmpeg_path
                else:
                    logger.warning("Existing FFmpeg is not functional, downloading new copy")

            # Download and verify FFmpeg
            logger.info("Downloading FFmpeg...")
            ffmpeg_path = self.downloader.download()
            if not self.downloader.verify():
                raise FFmpegError("Downloaded FFmpeg binary is not functional")
                
            # Set executable permissions
            try:
                if platform.system() != "Windows":
                    os.chmod(str(ffmpeg_path), 0o755)
            except Exception as e:
                logger.error(f"Failed to set FFmpeg permissions: {e}")
                
            return ffmpeg_path
            
        except Exception as e:
            logger.error(f"Failed to initialize FFmpeg: {e}")
            raise FFmpegError(f"Failed to initialize FFmpeg: {e}")

    def _verify_ffmpeg(self) -> None:
        """Verify FFmpeg functionality with comprehensive checks"""
        try:
            # Check FFmpeg version
            version_cmd = [str(self.ffmpeg_path), "-version"]
            result = subprocess.run(
                version_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                raise FFmpegError("FFmpeg version check failed")
            logger.info(f"FFmpeg version: {result.stdout.split()[2]}")

            # Check FFmpeg capabilities
            caps_cmd = [str(self.ffmpeg_path), "-hide_banner", "-encoders"]
            result = subprocess.run(
                caps_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                raise FFmpegError("FFmpeg capabilities check failed")

            # Verify encoders
            required_encoders = ["libx264"]
            if self._gpu_info["nvidia"]:
                required_encoders.append("h264_nvenc")
            elif self._gpu_info["amd"]:
                required_encoders.append("h264_amf")
            elif self._gpu_info["intel"]:
                required_encoders.append("h264_qsv")

            available_encoders = result.stdout.lower()
            missing_encoders = [
                encoder for encoder in required_encoders
                if encoder not in available_encoders
            ]
            
            if missing_encoders:
                logger.warning(f"Missing encoders: {', '.join(missing_encoders)}")
            
            logger.info("FFmpeg verification completed successfully")

        except subprocess.TimeoutExpired:
            raise FFmpegError("FFmpeg verification timed out")
        except Exception as e:
            raise FFmpegError(f"FFmpeg verification failed: {e}")

    def analyze_video(self, input_path: str) -> Dict[str, Any]:
        """Analyze video content for optimal encoding settings"""
        try:
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Input file not found: {input_path}")
            return self.video_analyzer.analyze_video(input_path)
        except Exception as e:
            logger.error(f"Video analysis failed: {e}")
            return {}

    def get_compression_params(self, input_path: str, target_size_mb: int) -> Dict[str, str]:
        """Get optimal compression parameters for the given input file"""
        try:
            # Analyze video first
            video_info = self.analyze_video(input_path)
            if not video_info:
                raise FFmpegError("Failed to analyze video")
                
            # Convert target size to bytes
            target_size_bytes = target_size_mb * 1024 * 1024
            
            # Get encoding parameters
            params = self.encoder_params.get_params(video_info, target_size_bytes)
            logger.info(f"Generated compression parameters: {params}")
            return params
            
        except Exception as e:
            logger.error(f"Failed to get compression parameters: {e}")
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
