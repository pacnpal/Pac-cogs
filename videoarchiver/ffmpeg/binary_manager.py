"""Module for managing FFmpeg binaries"""

import logging
import os
from pathlib import Path
from typing import Dict, Optional

from .exceptions import (
    FFmpegError,
    DownloadError,
    VerificationError,
    PermissionError,
    FFmpegNotFoundError
)
from .ffmpeg_downloader import FFmpegDownloader
from .verification_manager import VerificationManager

logger = logging.getLogger("FFmpegBinaryManager")

class BinaryManager:
    """Manages FFmpeg binary files and their lifecycle"""

    def __init__(
        self,
        base_dir: Path,
        system: str,
        machine: str,
        verification_manager: VerificationManager
    ):
        self.base_dir = base_dir
        self.verification_manager = verification_manager
        
        # Initialize downloader
        self.downloader = FFmpegDownloader(
            system=system,
            machine=machine,
            base_dir=base_dir
        )
        
        self._ffmpeg_path: Optional[Path] = None
        self._ffprobe_path: Optional[Path] = None

    def initialize_binaries(self, gpu_info: Dict[str, bool]) -> Dict[str, Path]:
        """Initialize FFmpeg and FFprobe binaries
        
        Args:
            gpu_info: Dictionary of GPU availability
            
        Returns:
            Dict[str, Path]: Paths to FFmpeg and FFprobe binaries
            
        Raises:
            FFmpegError: If initialization fails
        """
        try:
            # Verify existing binaries if they exist
            if self._verify_existing_binaries(gpu_info):
                return self._get_binary_paths()

            # Download and verify binaries
            logger.info("Downloading FFmpeg and FFprobe...")
            try:
                binaries = self.downloader.download()
                self._ffmpeg_path = binaries["ffmpeg"]
                self._ffprobe_path = binaries["ffprobe"]
            except Exception as e:
                raise DownloadError(f"Failed to download FFmpeg: {e}")

            # Verify downloaded binaries
            self._verify_binaries(gpu_info)
            
            return self._get_binary_paths()
            
        except Exception as e:
            logger.error(f"Failed to initialize binaries: {e}")
            if isinstance(e, (DownloadError, VerificationError, PermissionError)):
                raise
            raise FFmpegError(f"Failed to initialize binaries: {e}")

    def _verify_existing_binaries(self, gpu_info: Dict[str, bool]) -> bool:
        """Verify existing binary files if they exist
        
        Returns:
            bool: True if existing binaries are valid
        """
        if (self.downloader.ffmpeg_path.exists() and 
            self.downloader.ffprobe_path.exists()):
            logger.info(f"Found existing FFmpeg: {self.downloader.ffmpeg_path}")
            logger.info(f"Found existing FFprobe: {self.downloader.ffprobe_path}")
            
            try:
                self._ffmpeg_path = self.downloader.ffmpeg_path
                self._ffprobe_path = self.downloader.ffprobe_path
                self._verify_binaries(gpu_info)
                return True
            except Exception as e:
                logger.warning(f"Existing binaries verification failed: {e}")
                return False
        return False

    def _verify_binaries(self, gpu_info: Dict[str, bool]) -> None:
        """Verify binary files and set permissions"""
        try:
            # Set permissions
            self.verification_manager.verify_binary_permissions(self._ffmpeg_path)
            self.verification_manager.verify_binary_permissions(self._ffprobe_path)
            
            # Verify functionality
            self.verification_manager.verify_ffmpeg(
                self._ffmpeg_path,
                self._ffprobe_path,
                gpu_info
            )
        except Exception as e:
            self._ffmpeg_path = None
            self._ffprobe_path = None
            raise VerificationError(f"Binary verification failed: {e}")

    def _get_binary_paths(self) -> Dict[str, Path]:
        """Get paths to FFmpeg binaries
        
        Returns:
            Dict[str, Path]: Paths to FFmpeg and FFprobe binaries
            
        Raises:
            FFmpegNotFoundError: If binaries are not available
        """
        if not self._ffmpeg_path or not self._ffprobe_path:
            raise FFmpegNotFoundError("FFmpeg binaries not initialized")
            
        return {
            "ffmpeg": self._ffmpeg_path,
            "ffprobe": self._ffprobe_path
        }

    def force_download(self, gpu_info: Dict[str, bool]) -> bool:
        """Force re-download of FFmpeg binaries
        
        Returns:
            bool: True if download and verification successful
        """
        try:
            logger.info("Force downloading FFmpeg...")
            binaries = self.downloader.download()
            self._ffmpeg_path = binaries["ffmpeg"]
            self._ffprobe_path = binaries["ffprobe"]
            self._verify_binaries(gpu_info)
            return True
        except Exception as e:
            logger.error(f"Failed to force download FFmpeg: {e}")
            return False

    def get_ffmpeg_path(self) -> str:
        """Get path to FFmpeg binary"""
        if not self._ffmpeg_path or not self._ffmpeg_path.exists():
            raise FFmpegNotFoundError("FFmpeg is not available")
        return str(self._ffmpeg_path)

    def get_ffprobe_path(self) -> str:
        """Get path to FFprobe binary"""
        if not self._ffprobe_path or not self._ffprobe_path.exists():
            raise FFmpegNotFoundError("FFprobe is not available")
        return str(self._ffprobe_path)
