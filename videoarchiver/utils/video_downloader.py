"""Video download and processing utilities"""

import os
import logging
import asyncio
import ffmpeg
import yt_dlp
import shutil
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager
from videoarchiver.utils.exceptions import VideoVerificationError
from videoarchiver.utils.file_ops import secure_delete_file
from videoarchiver.utils.path_manager import temp_path_context

logger = logging.getLogger("VideoArchiver")

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
    ):
        self.download_path = download_path
        self.video_format = video_format
        self.max_quality = max_quality
        self.max_file_size = max_file_size
        self.enabled_sites = enabled_sites
        self.url_patterns = self._get_url_patterns()
        
        # Initialize FFmpeg manager
        self.ffmpeg_mgr = FFmpegManager()
        
        # Create thread pool for this instance
        self.download_pool = ThreadPoolExecutor(
            max_workers=max(1, min(5, concurrent_downloads)),
            thread_name_prefix="videoarchiver_download"
        )

        # Track active downloads for cleanup
        self.active_downloads: Dict[str, str] = {}
        self._downloads_lock = asyncio.Lock()

        # Configure yt-dlp options
        self.ydl_opts = {
            "format": f"bestvideo[height<={max_quality}]+bestaudio/best[height<={max_quality}]",
            "outtmpl": "%(title)s.%(ext)s",  # Base filename only, path added later
            "merge_output_format": video_format,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "concurrent_fragment_downloads": concurrent_downloads,
            "retries": self.MAX_RETRIES,
            "fragment_retries": self.MAX_RETRIES,
            "file_access_retries": self.FILE_OP_RETRIES,
            "extractor_retries": self.MAX_RETRIES,
            "postprocessor_hooks": [self._check_file_size],
            "progress_hooks": [self._progress_hook],
            "ffmpeg_location": self.ffmpeg_mgr.get_ffmpeg_path(),
        }

    def __del__(self):
        """Ensure thread pool is shutdown and files are cleaned up"""
        try:
            # Cancel all active downloads
            for file_path in self.active_downloads.values():
                try:
                    secure_delete_file(file_path)
                except Exception as e:
                    logger.error(f"Error deleting file during cleanup: {str(e)}")
            self.active_downloads.clear()

            # Shutdown thread pool
            if hasattr(self, 'download_pool'):
                self.download_pool.shutdown(wait=True)
        except Exception as e:
            logger.error(f"Error during VideoDownloader cleanup: {str(e)}")

    def _get_url_patterns(self) -> List[str]:
        """Get URL patterns for supported sites"""
        patterns = []
        try:
            with yt_dlp.YoutubeDL() as ydl:
                for extractor in ydl._ies:
                    if hasattr(extractor, "_VALID_URL") and extractor._VALID_URL:
                        if not self.enabled_sites or any(
                            site.lower() in extractor.IE_NAME.lower()
                            for site in self.enabled_sites
                        ):
                            patterns.append(extractor._VALID_URL)
        except Exception as e:
            logger.error(f"Error getting URL patterns: {str(e)}")
        return patterns

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

    def _verify_video_file(self, file_path: str) -> bool:
        """Verify video file integrity"""
        try:
            probe = ffmpeg.probe(file_path)
            # Check if file has video stream
            video_streams = [s for s in probe['streams'] if s['codec_type'] == 'video']
            if not video_streams:
                raise VideoVerificationError("No video streams found")
            # Check if duration is valid
            duration = float(probe['format'].get('duration', 0))
            if duration <= 0:
                raise VideoVerificationError("Invalid video duration")
            # Check if file is readable
            with open(file_path, 'rb') as f:
                f.seek(0, 2)  # Seek to end
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
                ydl_opts['outtmpl'] = os.path.join(temp_dir, ydl_opts['outtmpl'])

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.get_event_loop().run_in_executor(
                        self.download_pool,
                        lambda: ydl.extract_info(url, download=True)
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
                    await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))  # Exponential backoff
                else:
                    return False, "", f"All download attempts failed: {str(e)}"

    async def download_video(self, url: str) -> Tuple[bool, str, str]:
        """Download and process a video"""
        original_file = None
        compressed_file = None
        temp_dir = None

        try:
            # Create temporary directory for download
            with temp_path_context() as temp_dir:
                # Download the video
                success, file_path, error = await self._safe_download(url, temp_dir)
                if not success:
                    return False, "", error

                original_file = file_path

                # Track this download
                async with self._downloads_lock:
                    self.active_downloads[url] = original_file

                # Check file size and compress if needed
                file_size = os.path.getsize(original_file)
                if file_size > (self.max_file_size * 1024 * 1024):
                    logger.info(f"Compressing video: {original_file}")
                    try:
                        # Get optimal compression parameters
                        params = self.ffmpeg_mgr.get_compression_params(
                            original_file, self.max_file_size
                        )
                        compressed_file = os.path.join(
                            self.download_path,
                            f"compressed_{os.path.basename(original_file)}"
                        )

                        # Configure ffmpeg with optimal parameters
                        stream = ffmpeg.input(original_file)
                        stream = ffmpeg.output(stream, compressed_file, **params)

                        # Run compression in executor
                        await asyncio.get_event_loop().run_in_executor(
                            self.download_pool,
                            lambda: ffmpeg.run(
                                stream,
                                capture_stdout=True,
                                capture_stderr=True,
                                overwrite_output=True,
                            ),
                        )

                        if not os.path.exists(compressed_file):
                            raise FileNotFoundError("Compression completed but file not found")

                        # Verify compressed file
                        if not self._verify_video_file(compressed_file):
                            raise VideoVerificationError("Compressed file is not a valid video")

                        compressed_size = os.path.getsize(compressed_file)
                        if compressed_size <= (self.max_file_size * 1024 * 1024):
                            await self._safe_delete_file(original_file)
                            return True, compressed_file, ""
                        else:
                            await self._safe_delete_file(compressed_file)
                            return False, "", "Failed to compress to target size"
                    except Exception as e:
                        if compressed_file and os.path.exists(compressed_file):
                            await self._safe_delete_file(compressed_file)
                        logger.error(f"Compression error: {str(e)}")
                        return False, "", f"Compression error: {str(e)}"
                else:
                    # Move file to final location
                    final_path = os.path.join(self.download_path, os.path.basename(original_file))
                    # Use safe move with retries
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
                if compressed_file and os.path.exists(compressed_file) and not compressed_file.startswith(self.download_path):
                    await self._safe_delete_file(compressed_file)
            except Exception as e:
                logger.error(f"Error during file cleanup: {str(e)}")

    async def _safe_delete_file(self, file_path: str) -> bool:
        """Safely delete a file with retries"""
        for attempt in range(self.FILE_OP_RETRIES):
            try:
                if secure_delete_file(file_path):
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
                # Ensure destination directory exists
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # Try to move the file
                shutil.move(src, dst)
                return True
            except Exception as e:
                logger.error(f"Move attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.FILE_OP_RETRIES - 1:
                    return False
                await asyncio.sleep(self.FILE_OP_RETRY_DELAY * (attempt + 1))
        return False

    def is_supported_url(self, url: str) -> bool:
        """Check if URL is supported"""
        try:
            with yt_dlp.YoutubeDL() as ydl:
                # Get extractors
                extractors = ydl._ies
                # Try each extractor
                for extractor in extractors:
                    if hasattr(extractor, '_VALID_URL') and extractor._VALID_URL:
                        # Skip if site is not enabled
                        if self.enabled_sites and not any(
                            site.lower() in extractor.IE_NAME.lower()
                            for site in self.enabled_sites
                        ):
                            continue
                        # Try to match URL
                        if extractor.suitable(url):
                            return True
                return False
        except Exception as e:
            logger.error(f"Error checking URL support: {str(e)}")
            return False
