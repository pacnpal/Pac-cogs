"""Module for verifying FFmpeg functionality"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from videoarchiver.ffmpeg.exceptions import (
    TimeoutError,
    VerificationError,
    EncodingError,
    handle_ffmpeg_error
)

logger = logging.getLogger("FFmpegVerification")

class VerificationManager:
    """Handles verification of FFmpeg functionality"""

    def __init__(self, process_manager):
        self.process_manager = process_manager

    def verify_ffmpeg(
        self,
        ffmpeg_path: Path,
        ffprobe_path: Path,
        gpu_info: Dict[str, bool]
    ) -> None:
        """Verify FFmpeg functionality with comprehensive checks
        
        Args:
            ffmpeg_path: Path to FFmpeg binary
            ffprobe_path: Path to FFprobe binary
            gpu_info: Dictionary of GPU availability
            
        Raises:
            VerificationError: If verification fails
            TimeoutError: If verification times out
            EncodingError: If required encoders are missing
        """
        try:
            # Check FFmpeg version
            self._verify_ffmpeg_version(ffmpeg_path)
            
            # Check FFprobe version
            self._verify_ffprobe_version(ffprobe_path)
            
            # Check FFmpeg capabilities
            self._verify_ffmpeg_capabilities(ffmpeg_path, gpu_info)
            
            logger.info("FFmpeg verification completed successfully")

        except Exception as e:
            logger.error(f"FFmpeg verification failed: {e}")
            if isinstance(e, (TimeoutError, EncodingError, VerificationError)):
                raise
            raise VerificationError(f"FFmpeg verification failed: {e}")

    def _verify_ffmpeg_version(self, ffmpeg_path: Path) -> None:
        """Verify FFmpeg version"""
        try:
            result = self._execute_command(
                [str(ffmpeg_path), "-version"],
                "FFmpeg version check"
            )
            logger.info(f"FFmpeg version: {result.stdout.split()[2]}")
        except Exception as e:
            raise VerificationError(f"FFmpeg version check failed: {e}")

    def _verify_ffprobe_version(self, ffprobe_path: Path) -> None:
        """Verify FFprobe version"""
        try:
            result = self._execute_command(
                [str(ffprobe_path), "-version"],
                "FFprobe version check"
            )
            logger.info(f"FFprobe version: {result.stdout.split()[2]}")
        except Exception as e:
            raise VerificationError(f"FFprobe version check failed: {e}")

    def _verify_ffmpeg_capabilities(
        self,
        ffmpeg_path: Path,
        gpu_info: Dict[str, bool]
    ) -> None:
        """Verify FFmpeg capabilities and encoders"""
        try:
            result = self._execute_command(
                [str(ffmpeg_path), "-hide_banner", "-encoders"],
                "FFmpeg capabilities check"
            )

            # Verify required encoders
            required_encoders = self._get_required_encoders(gpu_info)
            available_encoders = result.stdout.lower()
            
            missing_encoders = [
                encoder for encoder in required_encoders
                if encoder not in available_encoders
            ]
            
            if missing_encoders:
                logger.warning(f"Missing encoders: {', '.join(missing_encoders)}")
                if "libx264" in missing_encoders:
                    raise EncodingError("Required encoder libx264 not available")

        except Exception as e:
            if isinstance(e, EncodingError):
                raise
            raise VerificationError(f"FFmpeg capabilities check failed: {e}")

    def _execute_command(
        self,
        command: List[str],
        operation: str,
        timeout: int = 10
    ) -> subprocess.CompletedProcess:
        """Execute a command with proper error handling"""
        try:
            result = self.process_manager.execute_command(
                command,
                timeout=timeout,
                check=False
            )

            if result.returncode != 0:
                error = handle_ffmpeg_error(result.stderr)
                logger.error(f"{operation} failed: {result.stderr}")
                raise error

            return result

        except subprocess.TimeoutExpired:
            raise TimeoutError(f"{operation} timed out")
        except Exception as e:
            if isinstance(e, (TimeoutError, EncodingError)):
                raise
            raise VerificationError(f"{operation} failed: {e}")

    def _get_required_encoders(self, gpu_info: Dict[str, bool]) -> List[str]:
        """Get list of required encoders based on GPU availability"""
        required_encoders = ["libx264"]
        
        if gpu_info["nvidia"]:
            required_encoders.append("h264_nvenc")
        elif gpu_info["amd"]:
            required_encoders.append("h264_amf")
        elif gpu_info["intel"]:
            required_encoders.append("h264_qsv")
            
        return required_encoders

    def verify_binary_permissions(self, binary_path: Path) -> None:
        """Verify and set binary permissions"""
        try:
            if os.name != "nt":  # Not Windows
                os.chmod(str(binary_path), 0o755)
        except Exception as e:
            raise VerificationError(f"Failed to set binary permissions: {e}")
