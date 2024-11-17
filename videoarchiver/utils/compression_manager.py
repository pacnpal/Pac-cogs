"""Manages video compression operations"""

import os
import asyncio
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List, Set, Tuple

from videoarchiver.processor import _compression_progress
from videoarchiver.utils.compression_handler import CompressionHandler
from videoarchiver.utils.progress_handler import ProgressHandler
from videoarchiver.utils.file_operations import FileOperations
from videoarchiver.utils.exceptions import CompressionError, VideoVerificationError

logger = logging.getLogger("VideoArchiver")

class CompressionManager:
    """Manages video compression operations"""

    def __init__(self, ffmpeg_mgr, max_file_size: int):
        self.ffmpeg_mgr = ffmpeg_mgr
        self.max_file_size = max_file_size * 1024 * 1024  # Convert to bytes
        self._active_processes: Set[subprocess.Popen] = set()
        self._processes_lock = asyncio.Lock()
        self._shutting_down = False

    async def compress_video(
        self,
        input_file: str,
        output_file: str,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> Tuple[bool, str]:
        """Compress a video file

        Args:
            input_file: Path to input video file
            output_file: Path to output video file
            progress_callback: Optional callback for compression progress

        Returns:
            Tuple[bool, str]: (Success status, Error message if any)
        """
        if self._shutting_down:
            return False, "Compression manager is shutting down"

        try:
            # Get optimal compression parameters
            compression_params = self.ffmpeg_mgr.get_compression_params(
                input_file, self.max_file_size // (1024 * 1024)  # Convert to MB
            )

            # Try hardware acceleration first
            success, error = await self._try_compression(
                input_file,
                output_file,
                compression_params,
                progress_callback,
                use_hardware=True,
            )

            # Fall back to CPU if hardware acceleration fails
            if not success:
                logger.warning(
                    f"Hardware acceleration failed: {error}, falling back to CPU encoding"
                )
                success, error = await self._try_compression(
                    input_file,
                    output_file,
                    compression_params,
                    progress_callback,
                    use_hardware=False,
                )

            if not success:
                return False, f"Compression failed: {error}"

            # Verify output file
            if not await self._verify_output(input_file, output_file):
                return False, "Output file verification failed"

            return True, ""

        except Exception as e:
            logger.error(f"Error during compression: {e}")
            return False, str(e)

    async def _try_compression(
        self,
        input_file: str,
        output_file: str,
        params: Dict[str, str],
        progress_callback: Optional[Callable[[float], None]],
        use_hardware: bool,
    ) -> Tuple[bool, str]:
        """Attempt video compression with given parameters"""
        if self._shutting_down:
            return False, "Compression manager is shutting down"

        try:
            # Build FFmpeg command
            cmd = await self._build_ffmpeg_command(
                input_file, output_file, params, use_hardware
            )

            # Get video duration for progress calculation
            duration = await self._get_video_duration(input_file)

            # Initialize compression progress tracking
            await self._init_compression_progress(
                input_file, params, use_hardware, duration
            )

            # Run compression
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            # Track the process
            async with self._processes_lock:
                self._active_processes.add(process)

            try:
                success = await self._monitor_compression(
                    process, input_file, output_file, duration, progress_callback
                )
                return success, ""

            finally:
                async with self._processes_lock:
                    self._active_processes.discard(process)

        except Exception as e:
            return False, str(e)

    async def _build_ffmpeg_command(
        self,
        input_file: str,
        output_file: str,
        params: Dict[str, str],
        use_hardware: bool,
    ) -> List[str]:
        """Build FFmpeg command with appropriate parameters"""
        ffmpeg_path = str(self.ffmpeg_mgr.get_ffmpeg_path())
        cmd = [ffmpeg_path, "-y", "-i", input_file, "-progress", "pipe:1"]

        # Modify parameters for hardware acceleration
        if use_hardware:
            gpu_info = self.ffmpeg_mgr.gpu_info
            if gpu_info["nvidia"] and params.get("c:v") == "libx264":
                params["c:v"] = "h264_nvenc"
            elif gpu_info["amd"] and params.get("c:v") == "libx264":
                params["c:v"] = "h264_amf"
            elif gpu_info["intel"] and params.get("c:v") == "libx264":
                params["c:v"] = "h264_qsv"
        else:
            params["c:v"] = "libx264"

        # Add parameters to command
        for key, value in params.items():
            cmd.extend([f"-{key}", str(value)])

        cmd.append(output_file)
        return cmd

    async def _monitor_compression(
        self,
        process: asyncio.subprocess.Process,
        input_file: str,
        output_file: str,
        duration: float,
        progress_callback: Optional[Callable[[float], None]],
    ) -> bool:
        """Monitor compression progress"""
        start_time = datetime.utcnow()

        while True:
            if self._shutting_down:
                process.terminate()
                return False

            line = await process.stdout.readline()
            if not line:
                break

            try:
                await self._update_progress(
                    line.decode().strip(),
                    input_file,
                    output_file,
                    duration,
                    start_time,
                    progress_callback,
                )
            except Exception as e:
                logger.error(f"Error updating progress: {e}")

        await process.wait()
        return os.path.exists(output_file)

    async def _verify_output(self, input_file: str, output_file: str) -> bool:
        """Verify compressed output file"""
        try:
            # Check file exists and is not empty
            if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                return False

            # Check file size is within limit
            if os.path.getsize(output_file) > self.max_file_size:
                return False

            # Verify video integrity
            return await self.ffmpeg_mgr.verify_video_file(output_file)

        except Exception as e:
            logger.error(f"Error verifying output file: {e}")
            return False

    async def cleanup(self) -> None:
        """Clean up resources"""
        self._shutting_down = True
        await self._terminate_processes()

    async def force_cleanup(self) -> None:
        """Force cleanup of resources"""
        self._shutting_down = True
        await self._kill_processes()

    async def _terminate_processes(self) -> None:
        """Terminate active processes gracefully"""
        async with self._processes_lock:
            for process in self._active_processes:
                try:
                    process.terminate()
                    await asyncio.sleep(0.1)
                    if process.returncode is None:
                        process.kill()
                except Exception as e:
                    logger.error(f"Error terminating process: {e}")
            self._active_processes.clear()

    async def _kill_processes(self) -> None:
        """Kill active processes immediately"""
        async with self._processes_lock:
            for process in self._active_processes:
                try:
                    process.kill()
                except Exception as e:
                    logger.error(f"Error killing process: {e}")
            self._active_processes.clear()

    async def _get_video_duration(self, file_path: str) -> float:
        """Get video duration in seconds"""
        try:
            return await self.ffmpeg_mgr.get_video_duration(file_path)
        except Exception as e:
            logger.error(f"Error getting video duration: {e}")
            return 0

    async def _init_compression_progress(
        self,
        input_file: str,
        params: Dict[str, str],
        use_hardware: bool,
        duration: float,
    ) -> None:
        """Initialize compression progress tracking"""
        _compression_progress[input_file] = {
            "active": True,
            "filename": os.path.basename(input_file),
            "start_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "percent": 0,
            "elapsed_time": "0:00",
            "input_size": os.path.getsize(input_file),
            "current_size": 0,
            "target_size": self.max_file_size,
            "codec": params.get("c:v", "unknown"),
            "hardware_accel": use_hardware,
            "preset": params.get("preset", "unknown"),
            "crf": params.get("crf", "unknown"),
            "duration": duration,
            "bitrate": params.get("b:v", "unknown"),
            "audio_codec": params.get("c:a", "unknown"),
            "audio_bitrate": params.get("b:a", "unknown"),
            "last_update": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def _update_progress(
        self,
        line: str,
        input_file: str,
        output_file: str,
        duration: float,
        start_time: datetime,
        progress_callback: Optional[Callable[[float], None]],
    ) -> None:
        """Update compression progress"""
        if line.startswith("out_time_ms="):
            current_time = int(line.split("=")[1]) / 1000000
            if duration > 0:
                progress = min(100, (current_time / duration) * 100)

                if input_file in _compression_progress:
                    elapsed = datetime.utcnow() - start_time
                    _compression_progress[input_file].update(
                        {
                            "percent": progress,
                            "elapsed_time": str(elapsed).split(".")[0],
                            "current_size": (
                                os.path.getsize(output_file)
                                if os.path.exists(output_file)
                                else 0
                            ),
                            "current_time": current_time,
                            "last_update": datetime.utcnow().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                        }
                    )

                if progress_callback:
                    progress_callback(progress)
