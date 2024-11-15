"""Main FFmpeg management module"""

import os
import platform
import multiprocessing
import logging
import subprocess
import traceback
import signal
import psutil
from pathlib import Path
from typing import Dict, Any, Optional, Set

from videoarchiver.ffmpeg.exceptions import (
    FFmpegError,
    DownloadError,
    VerificationError,
    EncodingError,
    AnalysisError,
    GPUError,
    HardwareAccelerationError,
    FFmpegNotFoundError,
    FFprobeError,
    CompressionError,
    FormatError,
    PermissionError,
    TimeoutError,
    ResourceError,
    QualityError,
    AudioError,
    BitrateError,
    handle_ffmpeg_error
)
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
        
        # Get or download FFmpeg and FFprobe
        binaries = self._initialize_binaries()
        self.ffmpeg_path = binaries["ffmpeg"]
        self.ffprobe_path = binaries["ffprobe"]
        logger.info(f"Using FFmpeg from: {self.ffmpeg_path}")
        logger.info(f"Using FFprobe from: {self.ffprobe_path}")
        
        # Initialize components
        self.gpu_detector = GPUDetector(self.ffmpeg_path)
        self.video_analyzer = VideoAnalyzer(self.ffmpeg_path)
        self._gpu_info = self.gpu_detector.detect_gpu()
        self._cpu_cores = multiprocessing.cpu_count()
        
        # Initialize encoder params
        self.encoder_params = EncoderParams(self._cpu_cores, self._gpu_info)

        # Track active FFmpeg processes
        self._active_processes: Set[subprocess.Popen] = set()
        
        # Verify FFmpeg functionality
        self._verify_ffmpeg()
        logger.info("FFmpeg manager initialized successfully")

    def kill_all_processes(self) -> None:
        """Kill all active FFmpeg processes"""
        try:
            # First try graceful termination
            for process in self._active_processes:
                try:
                    if process.poll() is None:  # Process is still running
                        process.terminate()
                except Exception as e:
                    logger.error(f"Error terminating FFmpeg process: {e}")

            # Give processes a moment to terminate
            import time
            time.sleep(0.5)

            # Force kill any remaining processes
            for process in self._active_processes:
                try:
                    if process.poll() is None:  # Process is still running
                        process.kill()
                except Exception as e:
                    logger.error(f"Error killing FFmpeg process: {e}")

            # Find and kill any orphaned FFmpeg processes
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'ffmpeg' in proc.info['name'].lower():
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
                except Exception as e:
                    logger.error(f"Error killing orphaned FFmpeg process: {e}")

            self._active_processes.clear()
            logger.info("All FFmpeg processes terminated")

        except Exception as e:
            logger.error(f"Error killing FFmpeg processes: {e}")

    def _initialize_binaries(self) -> Dict[str, Path]:
        """Initialize FFmpeg and FFprobe binaries with proper error handling"""
        try:
            # Verify existing binaries if they exist
            if self.downloader.ffmpeg_path.exists() and self.downloader.ffprobe_path.exists():
                logger.info(f"Found existing FFmpeg: {self.downloader.ffmpeg_path}")
                logger.info(f"Found existing FFprobe: {self.downloader.ffprobe_path}")
                if self.downloader.verify():
                    # Set executable permissions
                    if platform.system() != "Windows":
                        try:
                            os.chmod(str(self.downloader.ffmpeg_path), 0o755)
                            os.chmod(str(self.downloader.ffprobe_path), 0o755)
                        except Exception as e:
                            raise PermissionError(f"Failed to set binary permissions: {e}")
                    return {
                        "ffmpeg": self.downloader.ffmpeg_path,
                        "ffprobe": self.downloader.ffprobe_path
                    }
                else:
                    logger.warning("Existing binaries are not functional, downloading new copies")

            # Download and verify binaries
            logger.info("Downloading FFmpeg and FFprobe...")
            try:
                binaries = self.downloader.download()
            except Exception as e:
                raise DownloadError(f"Failed to download FFmpeg: {e}")

            if not self.downloader.verify():
                raise VerificationError("Downloaded binaries are not functional")
                
            # Set executable permissions
            try:
                if platform.system() != "Windows":
                    os.chmod(str(binaries["ffmpeg"]), 0o755)
                    os.chmod(str(binaries["ffprobe"]), 0o755)
            except Exception as e:
                raise PermissionError(f"Failed to set binary permissions: {e}")
                
            return binaries
            
        except Exception as e:
            logger.error(f"Failed to initialize binaries: {e}")
            if isinstance(e, (DownloadError, VerificationError, PermissionError)):
                raise
            raise FFmpegError(f"Failed to initialize binaries: {e}")

    def _verify_ffmpeg(self) -> None:
        """Verify FFmpeg functionality with comprehensive checks"""
        try:
            # Check FFmpeg version with enhanced error handling
            version_cmd = [str(self.ffmpeg_path), "-version"]
            try:
                result = subprocess.run(
                    version_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                    check=False,  # Don't raise on non-zero return code
                    env={"PATH": os.environ.get("PATH", "")}  # Ensure PATH is set
                )
            except subprocess.TimeoutExpired:
                raise TimeoutError("FFmpeg version check timed out")
            except Exception as e:
                raise VerificationError(f"FFmpeg version check failed: {e}")

            if result.returncode != 0:
                error = handle_ffmpeg_error(result.stderr)
                logger.error(f"FFmpeg version check failed: {result.stderr}")
                raise error

            logger.info(f"FFmpeg version: {result.stdout.split()[2]}")

            # Check FFprobe version with enhanced error handling
            probe_cmd = [str(self.ffprobe_path), "-version"]
            try:
                result = subprocess.run(
                    probe_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                    check=False,  # Don't raise on non-zero return code
                    env={"PATH": os.environ.get("PATH", "")}  # Ensure PATH is set
                )
            except subprocess.TimeoutExpired:
                raise TimeoutError("FFprobe version check timed out")
            except Exception as e:
                raise VerificationError(f"FFprobe version check failed: {e}")

            if result.returncode != 0:
                error = handle_ffmpeg_error(result.stderr)
                logger.error(f"FFprobe version check failed: {result.stderr}")
                raise error

            logger.info(f"FFprobe version: {result.stdout.split()[2]}")

            # Check FFmpeg capabilities with enhanced error handling
            caps_cmd = [str(self.ffmpeg_path), "-hide_banner", "-encoders"]
            try:
                result = subprocess.run(
                    caps_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                    check=False,  # Don't raise on non-zero return code
                    env={"PATH": os.environ.get("PATH", "")}  # Ensure PATH is set
                )
            except subprocess.TimeoutExpired:
                raise TimeoutError("FFmpeg capabilities check timed out")
            except Exception as e:
                raise VerificationError(f"FFmpeg capabilities check failed: {e}")

            if result.returncode != 0:
                error = handle_ffmpeg_error(result.stderr)
                logger.error(f"FFmpeg capabilities check failed: {result.stderr}")
                raise error

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
                if "libx264" in missing_encoders:
                    raise EncodingError("Required encoder libx264 not available")
            
            logger.info("FFmpeg verification completed successfully")

        except Exception as e:
            logger.error(f"FFmpeg verification failed: {traceback.format_exc()}")
            if isinstance(e, (TimeoutError, EncodingError, VerificationError)):
                raise
            raise VerificationError(f"FFmpeg verification failed: {e}")

    def analyze_video(self, input_path: str) -> Dict[str, Any]:
        """Analyze video content for optimal encoding settings"""
        try:
            if not os.path.exists(input_path):
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
        if not self.ffmpeg_path.exists():
            raise FFmpegNotFoundError("FFmpeg is not available")
        return str(self.ffmpeg_path)

    def get_ffprobe_path(self) -> str:
        """Get path to FFprobe binary"""
        if not self.ffprobe_path.exists():
            raise FFmpegNotFoundError("FFprobe is not available")
        return str(self.ffprobe_path)

    def force_download(self) -> bool:
        """Force re-download of FFmpeg binary"""
        try:
            logger.info("Force downloading FFmpeg...")
            binaries = self.downloader.download()
            self.ffmpeg_path = binaries["ffmpeg"]
            self.ffprobe_path = binaries["ffprobe"]
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
