"""Video compression handling utilities"""

import os
import asyncio
import logging
import subprocess
from datetime import datetime
from typing import Dict, Optional, Callable, Set, Tuple

from ..ffmpeg.ffmpeg_manager import FFmpegManager
from ..ffmpeg.exceptions import CompressionError
from ..utils.exceptions import VideoVerificationError
from ..utils.file_operations import FileOperations
from ..utils.progress_handler import ProgressHandler

logger = logging.getLogger("VideoArchiver")

class CompressionHandler:
    """Handles video compression operations"""

    def __init__(self, ffmpeg_mgr: FFmpegManager, progress_handler: ProgressHandler,
                 file_ops: FileOperations):
        self.ffmpeg_mgr = ffmpeg_mgr
        self.progress_handler = progress_handler
        self.file_ops = file_ops
        self._active_processes: Set[subprocess.Popen] = set()
        self._processes_lock = asyncio.Lock()
        self._shutting_down = False
        self.max_file_size = 0  # Will be set during compression

    async def cleanup(self) -> None:
        """Clean up compression resources"""
        self._shutting_down = True
        try:
            async with self._processes_lock:
                for process in self._active_processes:
                    try:
                        process.terminate()
                        await asyncio.sleep(0.1)
                        if process.poll() is None:
                            process.kill()
                    except Exception as e:
                        logger.error(f"Error killing compression process: {e}")
                self._active_processes.clear()
        finally:
            self._shutting_down = False

    async def compress_video(
        self,
        input_file: str,
        output_file: str,
        max_size_mb: int,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> Tuple[bool, str]:
        """Compress video to target size"""
        if self._shutting_down:
            return False, "Compression handler is shutting down"

        self.max_file_size = max_size_mb

        try:
            # Get optimal compression parameters
            compression_params = self.ffmpeg_mgr.get_compression_params(
                input_file, max_size_mb
            )

            # Try hardware acceleration first
            success = await self._try_compression(
                input_file,
                output_file,
                compression_params,
                progress_callback,
                use_hardware=True
            )

            # Fall back to CPU if hardware acceleration fails
            if not success:
                logger.warning("Hardware acceleration failed, falling back to CPU encoding")
                success = await self._try_compression(
                    input_file,
                    output_file,
                    compression_params,
                    progress_callback,
                    use_hardware=False
                )

            if not success:
                return False, "Failed to compress with both hardware and CPU encoding"

            # Verify compressed file
            if not self.file_ops.verify_video_file(output_file, str(self.ffmpeg_mgr.get_ffprobe_path())):
                return False, "Compressed file verification failed"

            # Check final size
            within_limit, final_size = self.file_ops.check_file_size(output_file, max_size_mb)
            if not within_limit:
                return False, f"Failed to compress to target size: {final_size} bytes"

            return True, ""

        except Exception as e:
            return False, str(e)

    async def _try_compression(
        self,
        input_file: str,
        output_file: str,
        params: Dict[str, str],
        progress_callback: Optional[Callable[[float], None]] = None,
        use_hardware: bool = True,
    ) -> bool:
        """Attempt video compression with given parameters"""
        if self._shutting_down:
            return False

        try:
            # Build FFmpeg command
            ffmpeg_path = str(self.ffmpeg_mgr.get_ffmpeg_path())
            cmd = [ffmpeg_path, "-y", "-i", input_file]

            # Add progress monitoring
            cmd.extend(["-progress", "pipe:1"])

            # Modify parameters based on hardware acceleration preference
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

            # Add all parameters to command
            for key, value in params.items():
                cmd.extend([f"-{key}", str(value)])

            # Add output file
            cmd.append(output_file)

            # Get video duration for progress calculation
            duration = self.file_ops.get_video_duration(input_file, str(self.ffmpeg_mgr.get_ffprobe_path()))

            # Initialize compression progress
            self.progress_handler.update(input_file, {
                "active": True,
                "filename": os.path.basename(input_file),
                "start_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "percent": 0,
                "elapsed_time": "0:00",
                "input_size": os.path.getsize(input_file),
                "current_size": 0,
                "target_size": self.max_file_size * 1024 * 1024,
                "codec": params.get("c:v", "unknown"),
                "hardware_accel": use_hardware,
                "preset": params.get("preset", "unknown"),
                "crf": params.get("crf", "unknown"),
                "duration": duration,
                "bitrate": params.get("b:v", "unknown"),
                "audio_codec": params.get("c:a", "unknown"),
                "audio_bitrate": params.get("b:a", "unknown"),
            })

            # Run compression with progress monitoring
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )

                # Track the process
                async with self._processes_lock:
                    self._active_processes.add(process)

                start_time = datetime.utcnow()

                while True:
                    if self._shutting_down:
                        process.terminate()
                        return False

                    line = await process.stdout.readline()
                    if not line:
                        break

                    try:
                        line = line.decode().strip()
                        if line.startswith("out_time_ms="):
                            current_time = int(line.split("=")[1]) / 1000000
                            self.progress_handler.handle_compression_progress(
                                input_file, current_time, duration,
                                output_file, start_time, progress_callback
                            )
                    except Exception as e:
                        logger.error(f"Error parsing FFmpeg progress: {e}")

                await process.wait()
                return os.path.exists(output_file)

            except Exception as e:
                logger.error(f"Error during compression process: {e}")
                return False
            finally:
                # Remove process from tracking
                async with self._processes_lock:
                    self._active_processes.discard(process)

        except Exception as e:
            logger.error(f"Compression attempt failed: {str(e)}")
            return False
