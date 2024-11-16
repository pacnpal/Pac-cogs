"""Core download functionality for video archiver"""

import os
import asyncio
import logging
import yt_dlp
from typing import Dict, Optional, Callable, Tuple
from pathlib import Path

from videoarchiver.utils.url_validator import check_url_support
from videoarchiver.utils.progress_handler import ProgressHandler, CancellableYTDLLogger
from videoarchiver.utils.file_operations import FileOperations
from videoarchiver.utils.compression_handler import CompressionHandler
from videoarchiver.utils.process_manager import ProcessManager
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager

logger = logging.getLogger("VideoArchiver")

class DownloadCore:
    """Core download functionality for video archiver"""

    def __init__(
        self,
        download_path: str,
        video_format: str,
        max_quality: int,
        max_file_size: int,
        enabled_sites: Optional[list[str]] = None,
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

        # Initialize components
        self.process_manager = ProcessManager(concurrent_downloads)
        self.progress_handler = ProgressHandler()
        self.file_ops = FileOperations()
        self.compression_handler = CompressionHandler(
            self.ffmpeg_mgr, self.progress_handler, self.file_ops
        )

        # Create cancellable logger
        self.ytdl_logger = CancellableYTDLLogger()

        # Configure yt-dlp options
        self.ydl_opts = self._configure_ydl_options()

    def _configure_ydl_options(self) -> Dict:
        """Configure yt-dlp options"""
        return {
            "format": f"bv*[height<={self.max_quality}][ext=mp4]+ba[ext=m4a]/b[height<={self.max_quality}]/best",
            "outtmpl": "%(title)s.%(ext)s",
            "merge_output_format": self.video_format,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "concurrent_fragment_downloads": 1,
            "retries": 5,
            "fragment_retries": 5,
            "file_access_retries": 3,
            "extractor_retries": 5,
            "postprocessor_hooks": [self._check_file_size],
            "progress_hooks": [self._handle_progress],
            "ffmpeg_location": str(self.ffmpeg_mgr.get_ffmpeg_path()),
            "ffprobe_location": str(self.ffmpeg_mgr.get_ffprobe_path()),
            "paths": {"home": str(self.download_path)},
            "logger": self.ytdl_logger,
            "ignoreerrors": True,
            "no_color": True,
            "geo_bypass": True,
            "socket_timeout": 60,
            "http_chunk_size": 1048576,
            "external_downloader_args": {"ffmpeg": ["-timeout", "60000000"]},
            "max_sleep_interval": 5,
            "sleep_interval": 1,
            "max_filesize": self.max_file_size * 1024 * 1024,
        }

    def _check_file_size(self, info: Dict) -> None:
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

    def _handle_progress(self, d: Dict) -> None:
        """Handle download progress updates"""
        url = d.get("info_dict", {}).get("webpage_url", "unknown")
        self.progress_handler.handle_download_progress(d, url)

    def is_supported_url(self, url: str) -> bool:
        """Check if URL is supported"""
        return check_url_support(url, self.ydl_opts, self.enabled_sites)

    async def download_video(
        self, url: str, progress_callback: Optional[Callable[[float], None]] = None
    ) -> Tuple[bool, str, str]:
        """Download and process a video"""
        if self.process_manager.is_shutting_down:
            return False, "", "Download manager is shutting down"

        # Initialize progress tracking
        self.progress_handler.initialize_progress(url)
        original_file = None
        compressed_file = None

        try:
            # Download the video
            success, file_path, error = await self._safe_download(
                url, str(self.download_path), progress_callback
            )
            if not success:
                return False, "", error

            original_file = file_path
            await self.process_manager.track_download(url, original_file)

            # Check file size and compress if needed
            within_limit, file_size = self.file_ops.check_file_size(original_file, self.max_file_size)
            if not within_limit:
                logger.info(f"Compressing video: {original_file}")
                try:
                    compressed_file = os.path.join(
                        self.download_path,
                        f"compressed_{os.path.basename(original_file)}",
                    )

                    # Attempt compression
                    success, error = await self.compression_handler.compress_video(
                        original_file,
                        compressed_file,
                        self.max_file_size,
                        progress_callback
                    )

                    if not success:
                        await self._cleanup_files(original_file, compressed_file)
                        return False, "", error

                    # Verify compressed file
                    if not self.file_ops.verify_video_file(
                        compressed_file, 
                        str(self.ffmpeg_mgr.get_ffprobe_path())
                    ):
                        await self._cleanup_files(original_file, compressed_file)
                        return False, "", "Compressed file verification failed"

                    # Delete original and return compressed
                    await self.file_ops.safe_delete_file(original_file)
                    return True, compressed_file, ""

                except Exception as e:
                    error_msg = f"Compression failed: {str(e)}"
                    await self._cleanup_files(original_file, compressed_file)
                    return False, "", error_msg
            else:
                # Move file to final location if no compression needed
                final_path = os.path.join(
                    self.download_path, 
                    os.path.basename(original_file)
                )
                success = await self.file_ops.safe_move_file(original_file, final_path)
                if not success:
                    await self._cleanup_files(original_file)
                    return False, "", "Failed to move file to final location"
                return True, final_path, ""

        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            await self._cleanup_files(original_file, compressed_file)
            return False, "", str(e)

        finally:
            # Clean up tracking
            await self.process_manager.untrack_download(url)
            self.progress_handler.complete(url)

    async def _safe_download(
        self,
        url: str,
        output_dir: str,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> Tuple[bool, str, str]:
        """Safely download video with retries"""
        if self.process_manager.is_shutting_down:
            return False, "", "Download manager is shutting down"

        last_error = None
        for attempt in range(5):  # Max retries
            try:
                ydl_opts = self.ydl_opts.copy()
                ydl_opts["outtmpl"] = os.path.join(output_dir, ydl_opts["outtmpl"])

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
                                progress_callback(percent)
                            except Exception as e:
                                logger.error(f"Error in progress callback: {e}")

                    ydl_opts["progress_hooks"] = [combined_progress_hook]

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.get_event_loop().run_in_executor(
                        self.process_manager.download_pool,
                        lambda: ydl.extract_info(url, download=True)
                    )

                if info is None:
                    raise Exception("Failed to extract video information")

                file_path = os.path.join(output_dir, ydl.prepare_filename(info))
                if not os.path.exists(file_path):
                    raise FileNotFoundError("Download completed but file not found")

                if not self.file_ops.verify_video_file(
                    file_path,
                    str(self.ffmpeg_mgr.get_ffprobe_path())
                ):
                    raise Exception("Downloaded file is not a valid video")

                return True, file_path, ""

            except Exception as e:
                last_error = str(e)
                logger.error(f"Download attempt {attempt + 1} failed: {str(e)}")
                if attempt < 4:  # Less than max retries
                    delay = 10 * (2**attempt) + (attempt * 2)  # Exponential backoff
                    await asyncio.sleep(delay)
                else:
                    return False, "", f"All download attempts failed: {last_error}"

    async def _cleanup_files(self, *files: str) -> None:
        """Clean up multiple files"""
        for file in files:
            if file and os.path.exists(file):
                await self.file_ops.safe_delete_file(file)

    async def cleanup(self) -> None:
        """Clean up resources"""
        await self.process_manager.cleanup()
        await self.compression_handler.cleanup()

    async def force_cleanup(self) -> None:
        """Force cleanup of all resources"""
        self.ytdl_logger.cancelled = True
        await self.process_m
        self.ytdl_logger.cancelled = True
        await self.process_manager.force_cleanup()
        await self.compress