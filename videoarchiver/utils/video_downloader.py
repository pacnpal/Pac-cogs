"""Video download and processing utilities"""

import os
import re
import logging
import asyncio
import ffmpeg
import yt_dlp
import shutil
import subprocess
import json
import signal
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple, Callable, Set
from pathlib import Path
from datetime import datetime

from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager
from videoarchiver.ffmpeg.exceptions import (
    FFmpegError,
    CompressionError,
    VerificationError,
    FFprobeError,
    TimeoutError,
    handle_ffmpeg_error,
)
from videoarchiver.utils.exceptions import VideoVerificationError
from videoarchiver.utils.file_ops import secure_delete_file
from videoarchiver.utils.path_manager import temp_path_context

logger = logging.getLogger("VideoArchiver")

# Add a custom yt-dlp logger to handle cancellation
class CancellableYTDLLogger:
    def __init__(self):
        self.cancelled = False

    def debug(self, msg):
        if self.cancelled:
            raise Exception("Download cancelled")
        logger.debug(msg)

    def warning(self, msg):
        if self.cancelled:
            raise Exception("Download cancelled")
        logger.warning(msg)

    def error(self, msg):
        if self.cancelled:
            raise Exception("Download cancelled")
        logger.error(msg)

def is_video_url_pattern(url: str) -> bool:
    """Check if URL matches common video platform patterns"""
    video_patterns = [
        r"youtube\.com/watch\?v=",
        r"youtu\.be/",
        r"vimeo\.com/",
        r"tiktok\.com/",
        r"twitter\.com/.*/video/",
        r"x\.com/.*/video/",
        r"bsky\.app/",
        r"facebook\.com/.*/videos/",
        r"instagram\.com/.*/(tv|reel|p)/",
        r"twitch\.tv/.*/clip/",
        r"streamable\.com/",
        r"v\.redd\.it/",
        r"clips\.twitch\.tv/",
        r"dailymotion\.com/video/",
        r"\.mp4$",
        r"\.webm$",
        r"\.mov$",
    ]
    return any(re.search(pattern, url, re.IGNORECASE) for pattern in video_patterns)

class VideoDownloader:
    MAX_RETRIES = 5
    RETRY_DELAY = 10
    FILE_OP_RETRIES = 3
    FILE_OP_RETRY_DELAY = 1
    SHUTDOWN_TIMEOUT = 15  # seconds

    def __init__(
        self,
        download_path: str,
        video_format: str,
        max_quality: int,
        max_file_size: int,
        enabled_sites: Optional[List[str]] = None,
        concurrent_downloads: int = 2,
        ffmpeg_mgr: Optional[FFmpegManager] = None,
    ):
        self.download_path = Path(download_path)
        self.download_path.mkdir(parents=True, exist_ok=True)
        os.chmod(str(self.download_path), 0o755)

        self.video_format = video_format
        self.max_quality = max_quality
        self.max_file_size = max_file_size
        self.enabled_sites = enabled_sites
        self.ffmpeg_mgr = ffmpeg_mgr or FFmpegManager()

        # Create thread pool with proper naming
        self.download_pool = ThreadPoolExecutor(
            max_workers=max(1, min(3, concurrent_downloads)),
            thread_name_prefix="videoarchiver_download",
        )

        # Track active downloads and processes
        self.active_downloads: Dict[str, Dict[str, Any]] = {}
        self._downloads_lock = asyncio.Lock()
        self._active_processes: Set[subprocess.Popen] = set()
        self._processes_lock = asyncio.Lock()
        self._shutting_down = False

        # Create cancellable logger
        self.ytdl_logger = CancellableYTDLLogger()

        # Configure yt-dlp options
        self.ydl_opts = {
            "format": f"bv*[height<={max_quality}][ext=mp4]+ba[ext=m4a]/b[height<={max_quality}]/best",
            "outtmpl": "%(title)s.%(ext)s",
            "merge_output_format": video_format,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "concurrent_fragment_downloads": 1,
            "retries": self.MAX_RETRIES,
            "fragment_retries": self.MAX_RETRIES,
            "file_access_retries": self.FILE_OP_RETRIES,
            "extractor_retries": self.MAX_RETRIES,
            "postprocessor_hooks": [self._check_file_size],
            "progress_hooks": [self._progress_hook, self._detailed_progress_hook],
            "ffmpeg_location": str(self.ffmpeg_mgr.get_ffmpeg_path()),
            "ffprobe_location": str(self.ffmpeg_mgr.get_ffprobe_path()),
            "paths": {"home": str(self.download_path)},
            "logger": self.ytdl_logger,
            "ignoreerrors": True,
            "no_color": True,
            "geo_bypass": True,
            "socket_timeout": 60,
            "http_chunk_size": 1048576,
            "external_downloader_args": {
                "ffmpeg": ["-timeout", "60000000"]
            },
            "max_sleep_interval": 5,
            "sleep_interval": 1,
            "max_filesize": max_file_size * 1024 * 1024,
        }

    async def cleanup(self) -> None:
        """Clean up resources with proper shutdown"""
        self._shutting_down = True
        
        try:
            # Cancel active downloads
            self.ytdl_logger.cancelled = True
            
            # Kill any active FFmpeg processes
            async with self._processes_lock:
                for process in self._active_processes:
                    try:
                        process.terminate()
                        await asyncio.sleep(0.1)  # Give process time to terminate
                        if process.poll() is None:
                            process.kill()  # Force kill if still running
                    except Exception as e:
                        logger.error(f"Error killing process: {e}")
                self._active_processes.clear()

            # Clean up thread pool
            self.download_pool.shutdown(wait=False, cancel_futures=True)

            # Clean up active downloads
            async with self._downloads_lock:
                self.active_downloads.clear()

        except Exception as e:
            logger.error(f"Error during downloader cleanup: {e}")
        finally:
            self._shutting_down = False

    async def force_cleanup(self) -> None:
        """Force cleanup of all resources"""
        try:
            # Force cancel all downloads
            self.ytdl_logger.cancelled = True
            
            # Kill all processes immediately
            async with self._processes_lock:
                for process in self._active_processes:
                    try:
                        process.kill()
                    except Exception as e:
                        logger.error(f"Error force killing process: {e}")
                self._active_processes.clear()

            # Force shutdown thread pool
            self.download_pool.shutdown(wait=False, cancel_futures=True)

            # Clear all tracking
            async with self._downloads_lock:
                self.active_downloads.clear()

        except Exception as e:
            logger.error(f"Error during force cleanup: {e}")

    def _detailed_progress_hook(self, d):
        """Handle detailed download progress tracking"""
        try:
            if d["status"] == "downloading":
                # Get URL from info dict
                url = d.get("info_dict", {}).get("webpage_url", "unknown")
                
                # Update global progress tracking
                from videoarchiver.processor import _download_progress
                
                if url in _download_progress:
                    _download_progress[url].update({
                        'active': True,
                        'percent': float(d.get("_percent_str", "0").replace('%', '')),
                        'speed': d.get("_speed_str", "N/A"),
                        'eta': d.get("_eta_str", "N/A"),
                        'downloaded_bytes': d.get("downloaded_bytes", 0),
                        'total_bytes': d.get("total_bytes", 0) or d.get("total_bytes_estimate", 0),
                        'retries': d.get("retry_count", 0),
                        'fragment_count': d.get("fragment_count", 0),
                        'fragment_index': d.get("fragment_index", 0),
                        'video_title': d.get("info_dict", {}).get("title", "Unknown"),
                        'extractor': d.get("info_dict", {}).get("extractor", "Unknown"),
                        'format': d.get("info_dict", {}).get("format", "Unknown"),
                        'resolution': d.get("info_dict", {}).get("resolution", "Unknown"),
                        'fps': d.get("info_dict", {}).get("fps", "Unknown"),
                        'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    
                    logger.debug(
                        f"Detailed progress for {url}: "
                        f"{_download_progress[url]['percent']}% at {_download_progress[url]['speed']}, "
                        f"ETA: {_download_progress[url]['eta']}"
                    )
        except Exception as e:
            logger.error(f"Error in detailed progress hook: {str(e)}")

    def _progress_hook(self, d):
        """Handle download progress"""
        if d["status"] == "finished":
            logger.info(f"Download completed: {d['filename']}")
        elif d["status"] == "downloading":
            try:
                percent = float(d.get("_percent_str", "0").replace("%", ""))
                speed = d.get("_speed_str", "N/A")
                eta = d.get("_eta_str", "N/A")
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes", 0) or d.get("total_bytes_estimate", 0)

                logger.debug(
                    f"Download progress: {percent}% at {speed}, "
                    f"ETA: {eta}, Downloaded: {downloaded}/{total} bytes"
                )
            except Exception as e:
                logger.debug(f"Error logging progress: {str(e)}")

    def is_supported_url(self, url: str) -> bool:
        """Check if URL is supported by attempting a simulated download"""
        if not is_video_url_pattern(url):
            return False

        try:
            simulate_opts = {
                **self.ydl_opts,
                "simulate": True,
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "skip_download": True,
                "format": "best",
            }

            with yt_dlp.YoutubeDL(simulate_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                    if info is None:
                        return False

                    if self.enabled_sites:
                        extractor = info.get("extractor", "").lower()
                        if not any(
                            site.lower() in extractor for site in self.enabled_sites
                        ):
                            logger.info(f"Site {extractor} not in enabled sites list")
                            return False

                    logger.info(
                        f"URL supported: {url} (Extractor: {info.get('extractor', 'unknown')})"
                    )
                    return True

                except yt_dlp.utils.UnsupportedError:
                    return False
                except Exception as e:
                    if "Unsupported URL" not in str(e):
                        logger.error(f"Error checking URL {url}: {str(e)}")
                    return False

        except Exception as e:
            logger.error(f"Error during URL check: {str(e)}")
            return False

    async def download_video(
        self, url: str, progress_callback: Optional[Callable[[float], None]] = None
    ) -> Tuple[bool, str, str]:
        """Download and process a video with improved error handling"""
        if self._shutting_down:
            return False, "", "Downloader is shutting down"

        # Initialize progress tracking for this URL
        from videoarchiver.processor import _download_progress
        _download_progress[url] = {
            'active': True,
            'start_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'percent': 0,
            'speed': 'N/A',
            'eta': 'N/A',
            'downloaded_bytes': 0,
            'total_bytes': 0,
            'retries': 0,
            'fragment_count': 0,
            'fragment_index': 0,
            'video_title': 'Unknown',
            'extractor': 'Unknown',
            'format': 'Unknown',
            'resolution': 'Unknown',
            'fps': 'Unknown',
            'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        }

        original_file = None
        compressed_file = None
        temp_dir = None
        hardware_accel_failed = False
        compression_params = None

        try:
            with temp_path_context() as temp_dir:
                # Download the video
                success, file_path, error = await self._safe_download(
                    url, temp_dir, progress_callback
                )
                if not success:
                    return False, "", error

                original_file = file_path

                async with self._downloads_lock:
                    self.active_downloads[url] = {
                        'file_path': original_file,
                        'start_time': datetime.utcnow()
                    }

                # Check file size and compress if needed
                file_size = os.path.getsize(original_file)
                if file_size > (self.max_file_size * 1024 * 1024):
                    logger.info(f"Compressing video: {original_file}")
                    try:
                        # Get optimal compression parameters
                        compression_params = self.ffmpeg_mgr.get_compression_params(
                            original_file, self.max_file_size
                        )
                        compressed_file = os.path.join(
                            self.download_path,
                            f"compressed_{os.path.basename(original_file)}",
                        )

                        # Try hardware acceleration first
                        success = await self._try_compression(
                            original_file,
                            compressed_file,
                            compression_params,
                            progress_callback,
                            use_hardware=True,
                        )

                        # If hardware acceleration fails, fall back to CPU
                        if not success:
                            hardware_accel_failed = True
                            logger.warning(
                                "Hardware acceleration failed, falling back to CPU encoding"
                            )
                            success = await self._try_compression(
                                original_file,
                                compressed_file,
                                compression_params,
                                progress_callback,
                                use_hardware=False,
                            )

                        if not success:
                            raise CompressionError(
                                "Failed to compress with both hardware and CPU encoding",
                                file_size,
                                self.max_file_size * 1024 * 1024,
                            )

                        # Verify compressed file
                        if not self._verify_video_file(compressed_file):
                            raise VideoVerificationError(
                                "Compressed file verification failed"
                            )

                        compressed_size = os.path.getsize(compressed_file)
                        if compressed_size <= (self.max_file_size * 1024 * 1024):
                            await self._safe_delete_file(original_file)
                            return True, compressed_file, ""
                        else:
                            await self._safe_delete_file(compressed_file)
                            raise CompressionError(
                                "Failed to compress to target size",
                                file_size,
                                self.max_file_size * 1024 * 1024,
                            )

                    except Exception as e:
                        error_msg = str(e)
                        if hardware_accel_failed:
                            error_msg = f"Hardware acceleration failed, CPU fallback error: {error_msg}"
                        if compressed_file and os.path.exists(compressed_file):
                            await self._safe_delete_file(compressed_file)
                        return False, "", error_msg

                else:
                    # Move file to final location
                    final_path = os.path.join(
                        self.download_path, os.path.basename(original_file)
                    )
                    success = await self._safe_move_file(original_file, final_path)
                    if not success:
                        return False, "", "Failed to move file to final location"
                    return True, final_path, ""

        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return False, "", str(e)

        finally:
            # Clean up
            async with self._downloads_lock:
                self.active_downloads.pop(url, None)
                if url in _download_progress:
                    _download_progress[url]['active'] = False

            try:
                if original_file and os.path.exists(original_file):
                    await self._safe_delete_file(original_file)
                if (
                    compressed_file
                    and os.path.exists(compressed_file)
                    and not compressed_file.startswith(self.download_path)
                ):
                    await self._safe_delete_file(compressed_file)
            except Exception as e:
                logger.error(f"Error during file cleanup: {str(e)}")

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
            duration = self._get_video_duration(input_file)

            # Update compression progress tracking
            from videoarchiver.processor import _compression_progress
            
            # Get input file size
            input_size = os.path.getsize(input_file)
            
            # Initialize compression progress
            _compression_progress[input_file] = {
                'active': True,
                'filename': os.path.basename(input_file),
                'start_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'percent': 0,
                'elapsed_time': '0:00',
                'input_size': input_size,
                'current_size': 0,
                'target_size': self.max_file_size * 1024 * 1024,
                'codec': params.get('c:v', 'unknown'),
                'hardware_accel': use_hardware,
                'preset': params.get('preset', 'unknown'),
                'crf': params.get('crf', 'unknown'),
                'duration': duration,
                'bitrate': params.get('b:v', 'unknown'),
                'audio_codec': params.get('c:a', 'unknown'),
                'audio_bitrate': params.get('b:a', 'unknown'),
                'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }

            # Run compression with progress monitoring
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            # Track the process
            async with self._processes_lock:
                self._active_processes.add(process)

            start_time = datetime.utcnow()
            loop = asyncio.get_running_loop()

            try:
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
                            current_time = (
                                int(line.split("=")[1]) / 1000000
                            )  # Convert microseconds to seconds
                            if duration > 0:
                                progress = min(100, (current_time / duration) * 100)
                                
                                # Update compression progress
                                elapsed = datetime.utcnow() - start_time
                                _compression_progress[input_file].update({
                                    'percent': progress,
                                    'elapsed_time': str(elapsed).split('.')[0],  # Remove microseconds
                                    'current_size': os.path.getsize(output_file) if os.path.exists(output_file) else 0,
                                    'current_time': current_time,
                                    'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                                })
                                
                                if progress_callback:
                                    # Call the callback directly since it now handles task creation
                                    progress_callback(progress)

                    except Exception as e:
                        logger.error(f"Error parsing FFmpeg progress: {e}")

                await process.wait()
                success = os.path.exists(output_file)
                
                # Update final status
                if success and input_file in _compression_progress:
                    _compression_progress[input_file].update({
                        'active': False,
                        'percent': 100,
                        'current_size': os.path.getsize(output_file),
                        'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    })
                
                return success

            finally:
                # Remove process from tracking
                async with self._processes_lock:
                    self._active_processes.discard(process)

        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg compression failed: {e.stderr.decode()}")
            return False
        except Exception as e:
            logger.error(f"Compression attempt failed: {str(e)}")
            return False
        finally:
            # Ensure compression progress is marked as inactive
            if input_file in _compression_progress:
                _compression_progress[input_file]['active'] = False

    def _get_video_duration(self, file_path: str) -> float:
        """Get video duration in seconds"""
        try:
            ffprobe_path = str(self.ffmpeg_mgr.get_ffprobe_path())
            cmd = [
                ffprobe_path,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                file_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except Exception as e:
            logger.error(f"Error getting video duration: {e}")
            return 0

    def _check_file_size(self, info):
        """Check if file size is within limits"""
        if info.get("filepath") and os.path.exists(info["filepath"]):
            try:
                size = os.path.getsize(info["filepath"])
                if size > (self.max_file_size * 1024 * 1024):
                    logger.info(
                        f"File exceeds size limit, will compress: {info['filepath']}"
                    )
            except OSError as e:
                logger.error(f"Error checking file size: {str(e)}")

    def _verify_video_file(self, file_path: str) -> bool:
        """Verify video file integrity"""
        try:
            ffprobe_path = str(self.ffmpeg_mgr.get_ffprobe_path())
            cmd = [
                ffprobe_path,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                file_path,
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                raise VideoVerificationError(f"FFprobe failed: {result.stderr}")

            probe = json.loads(result.stdout)

            # Verify video stream
            video_streams = [s for s in probe["streams"] if s["codec_type"] == "video"]
            if not video_streams:
                raise VideoVerificationError("No video streams found")

            # Verify duration
            duration = float(probe["format"].get("duration", 0))
            if duration <= 0:
                raise VideoVerificationError("Invalid video duration")

            # Verify file is readable
            with open(file_path, "rb") as f:
                f.seek(0, 2)
                if f.tell() == 0:
                    raise VideoVerificationError("Empty file")

            return True

        except Exception as e:
            logger.error(f"Error verifying video file {file_path}: {e}")
            return False

    async def _safe_download(
        self,
        url: str,
        temp_dir: str,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> Tuple[bool, str, str]:
        """Safely download video with retries"""
        if self._shutting_down:
            return False, "", "Downloader is shutting down"

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                ydl_opts = self.ydl_opts.copy()
                ydl_opts["outtmpl"] = os.path.join(temp_dir, ydl_opts["outtmpl"])

                # Add progress callback
                if progress_callback:
                    original_progress_hook = ydl_opts["progress_hooks"][0]

                    def combined_progress_hook(d):
                        original_progress_hook(d)
                        if d["status"] == "downloading":
                            try:
                                percent = float(
                                    d.get("_percent_str", "0").replace("%", "")
                                )
                                # Call the callback directly since it now handles task creation
                                progress_callback(percent)
                            except Exception as e:
                                logger.error(f"Error in progress callback: {e}")

                    ydl_opts["progress_hooks"] = [combined_progress_hook]

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.get_event_loop().run_in_executor(
                        self.download_pool, lambda: ydl.extract_info(url, download=True)
                    )

                if info is None:
                    raise Exception("Failed to extract video information")

                file_path = os.path.join(temp_dir, ydl.prepare_filename(info))
                if not os.path.exists(file_path):
                    raise FileNotFoundError("Download completed but file not found")

                if not self._verify_video_file(file_path):
                    raise VideoVerificationError("Downloaded file is not a valid video")

                return True, file_path, ""

            except Exception as e:
                last_error = str(e)
                logger.error(f"Download attempt {attempt + 1} failed: {str(e)}")
                if attempt < self.MAX_RETRIES - 1:
                    # Exponential backoff with jitter
                    delay = self.RETRY_DELAY * (2**attempt) + (attempt * 2)
                    await asyncio.sleep(delay)
                else:
                    return False, "", f"All download attempts failed: {last_error}"

    async def _safe_delete_file(self, file_path: str) -> bool:
        """Safely delete a file with retries"""
        for attempt in range(self.FILE_OP_RETRIES):
            try:
                if await secure_delete_file(file_path):
                    return True
                await asyncio.sleep(self.FILE_OP_RETRY_DELAY * (attempt + 1))
            except Exception as e:
                logger.error(f"Delete attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.FILE_OP_RETRIES - 1:
                    return False
                await asyncio.sleep(self.FILE_OP_RETRY_DELAY * (attempt + 1))
        return False

    async def _safe_move_file(self, src: str, dst: str) -> bool:
        """Safely move a file with retries"""
        for attempt in range(self.FILE_OP_RETRIES):
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                return True
            except Exception as e:
                logger.error(f"Move attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.FILE_OP_RETRIES - 1:
                    return False
                await asyncio.sleep(self.FILE_OP_RETRY_DELAY * (attempt + 1))
        return False
