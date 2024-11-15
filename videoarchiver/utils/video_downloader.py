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
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple
from pathlib import Path

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
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds
    FILE_OP_RETRIES = 3
    FILE_OP_RETRY_DELAY = 1  # seconds

    def __init__(
        self,
        download_path: str,
        video_format: str,
        max_quality: int,
        max_file_size: int,
        enabled_sites: Optional[List[str]] = None,
        concurrent_downloads: int = 3,
        ffmpeg_mgr: Optional[FFmpegManager] = None,
    ):
        # Ensure download path exists with proper permissions
        self.download_path = Path(download_path)
        self.download_path.mkdir(parents=True, exist_ok=True)
        os.chmod(str(self.download_path), 0o755)
        logger.info(f"Initialized download directory: {self.download_path}")

        self.video_format = video_format
        self.max_quality = max_quality
        self.max_file_size = max_file_size
        self.enabled_sites = enabled_sites

        # Initialize FFmpeg manager
        self.ffmpeg_mgr = ffmpeg_mgr or FFmpegManager()
        logger.info(f"Using FFmpeg from: {self.ffmpeg_mgr.get_ffmpeg_path()}")

        # Create thread pool for this instance
        self.download_pool = ThreadPoolExecutor(
            max_workers=max(1, min(5, concurrent_downloads)),
            thread_name_prefix="videoarchiver_download",
        )

        # Track active downloads for cleanup
        self.active_downloads: Dict[str, str] = {}
        self._downloads_lock = asyncio.Lock()

        # Configure yt-dlp options with improved settings
        self.ydl_opts = {
            "format": f"bv*[height<={max_quality}][ext=mp4]+ba[ext=m4a]/b[height<={max_quality}]/best",
            "outtmpl": "%(title)s.%(ext)s",
            "merge_output_format": video_format,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "concurrent_fragment_downloads": concurrent_downloads,
            "retries": self.MAX_RETRIES,
            "fragment_retries": self.MAX_RETRIES,
            "file_access_retries": self.FILE_OP_RETRIES,
            "extractor_retries": self.MAX_RETRIES,
            "postprocessor_hooks": [self._check_file_size],
            "progress_hooks": [self._progress_hook],
            "ffmpeg_location": str(self.ffmpeg_mgr.get_ffmpeg_path()),
            "ffprobe_location": str(self.ffmpeg_mgr.get_ffprobe_path()),
            "paths": {"home": str(self.download_path)},
            "logger": logger,
            "ignoreerrors": True,
            "no_color": True,
            "geo_bypass": True,
            "socket_timeout": 30,
            "http_chunk_size": 10485760,  # 10MB chunks for better stability
            "external_downloader_args": {
                "ffmpeg": ["-timeout", "30000000"]  # 30 second timeout
            }
        }

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

    async def download_video(self, url: str) -> Tuple[bool, str, str]:
        """Download and process a video with improved error handling and retry logic"""
        original_file = None
        compressed_file = None
        temp_dir = None
        hardware_accel_failed = False
        compression_params = None

        try:
            with temp_path_context() as temp_dir:
                # Download the video
                success, file_path, error = await self._safe_download(url, temp_dir)
                if not success:
                    return False, "", error

                original_file = file_path

                async with self._downloads_lock:
                    self.active_downloads[url] = original_file

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
                            use_hardware=True
                        )

                        # If hardware acceleration fails, fall back to CPU
                        if not success:
                            hardware_accel_failed = True
                            logger.warning("Hardware acceleration failed, falling back to CPU encoding")
                            success = await self._try_compression(
                                original_file,
                                compressed_file,
                                compression_params,
                                use_hardware=False
                            )

                        if not success:
                            raise CompressionError(
                                "Failed to compress with both hardware and CPU encoding"
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
                                input_size=file_size,
                                target_size=self.max_file_size * 1024 * 1024,
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
        use_hardware: bool = True
    ) -> bool:
        """Attempt video compression with given parameters"""
        try:
            # Build FFmpeg command
            ffmpeg_path = str(self.ffmpeg_mgr.get_ffmpeg_path())
            cmd = [ffmpeg_path, "-y", "-i", input_file]

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

            # Run compression
            logger.debug(f"Running FFmpeg command: {' '.join(cmd)}")
            result = await asyncio.get_event_loop().run_in_executor(
                self.download_pool,
                lambda: subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                ),
            )

            return os.path.exists(output_file)

        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg compression failed: {e.stderr.decode()}")
            return False
        except Exception as e:
            logger.error(f"Compression attempt failed: {str(e)}")
            return False

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

    def _progress_hook(self, d):
        """Handle download progress"""
        if d["status"] == "finished":
            logger.info(f"Download completed: {d['filename']}")
        elif d["status"] == "downloading":
            try:
                percent = d.get("_percent_str", "N/A")
                speed = d.get("_speed_str", "N/A")
                eta = d.get("_eta_str", "N/A")
                logger.debug(f"Download progress: {percent} at {speed}, ETA: {eta}")
            except Exception as e:
                logger.debug(f"Error logging progress: {str(e)}")

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

    async def _safe_download(self, url: str, temp_dir: str) -> Tuple[bool, str, str]:
        """Safely download video with retries"""
        for attempt in range(self.MAX_RETRIES):
            try:
                ydl_opts = self.ydl_opts.copy()
                ydl_opts["outtmpl"] = os.path.join(temp_dir, ydl_opts["outtmpl"])

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
                logger.error(f"Download attempt {attempt + 1} failed: {str(e)}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    return False, "", f"All download attempts failed: {str(e)}"

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
