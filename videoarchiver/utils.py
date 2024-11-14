import os
import shutil
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
import yt_dlp
import ffmpeg
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from .ffmpeg_manager import FFmpegManager

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("VideoArchiver")

# Initialize FFmpeg manager
ffmpeg_mgr = FFmpegManager()


class VideoDownloader:
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
        
        # Create thread pool for this instance
        self.download_pool = ThreadPoolExecutor(
            max_workers=max(1, min(5, concurrent_downloads)),
            thread_name_prefix="videoarchiver_download"
        )

        # Configure yt-dlp options
        self.ydl_opts = {
            "format": f"bestvideo[height<={max_quality}]+bestaudio/best[height<={max_quality}]",
            "outtmpl": os.path.join(download_path, "%(title)s.%(ext)s"),
            "merge_output_format": video_format,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "concurrent_fragment_downloads": concurrent_downloads,
            "postprocessor_hooks": [self._check_file_size],
            "progress_hooks": [self._progress_hook],
            "ffmpeg_location": ffmpeg_mgr.get_ffmpeg_path(),
        }

    def __del__(self):
        """Ensure thread pool is shutdown"""
        try:
            if hasattr(self, 'download_pool'):
                self.download_pool.shutdown(wait=False)
        except Exception as e:
            logger.error(f"Error shutting down download pool: {str(e)}")

    def _get_url_patterns(self) -> List[str]:
        """Get URL patterns for supported sites"""
        patterns = []
        with yt_dlp.YoutubeDL() as ydl:
            for extractor in ydl._ies:
                if hasattr(extractor, "_VALID_URL") and extractor._VALID_URL:
                    if not self.enabled_sites or any(
                        site.lower() in extractor.IE_NAME.lower()
                        for site in self.enabled_sites
                    ):
                        patterns.append(extractor._VALID_URL)
        return patterns

    def _check_file_size(self, info):
        """Check if file size is within limits"""
        if info.get("filepath") and os.path.exists(info["filepath"]):
            size = os.path.getsize(info["filepath"])
            if size > (self.max_file_size * 1024 * 1024):
                logger.info(
                    f"File exceeds size limit, will compress: {info['filepath']}"
                )

    def _progress_hook(self, d):
        """Handle download progress"""
        if d["status"] == "finished":
            logger.info(f"Download completed: {d['filename']}")

    async def download_video(self, url: str) -> Tuple[bool, str, str]:
        """Download and process a video"""
        original_file = None
        compressed_file = None

        try:
            # Configure yt-dlp for this download
            ydl_opts = self.ydl_opts.copy()

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Run download in executor to prevent blocking
                info = await asyncio.get_event_loop().run_in_executor(
                    self.download_pool, lambda: ydl.extract_info(url, download=True)
                )

                if info is None:
                    return False, "", "Failed to extract video information"

                original_file = os.path.join(
                    self.download_path, ydl.prepare_filename(info)
                )

                if not os.path.exists(original_file):
                    return False, "", "Download completed but file not found"

                # Check file size and compress if needed
                file_size = os.path.getsize(original_file)
                if file_size > (self.max_file_size * 1024 * 1024):
                    logger.info(f"Compressing video: {original_file}")
                    try:
                        # Get optimal compression parameters
                        params = ffmpeg_mgr.get_compression_params(
                            original_file, self.max_file_size
                        )
                        compressed_file = (
                            original_file + ".compressed." + self.video_format
                        )

                        # Configure ffmpeg with optimal parameters
                        stream = ffmpeg.input(original_file)
                        stream = ffmpeg.output(stream, compressed_file, **params)

                        # Run compression in executor
                        await asyncio.get_event_loop().run_in_executor(
                            self.download_pool,  # Reuse download pool for compression
                            lambda: ffmpeg.run(
                                stream,
                                capture_stdout=True,
                                capture_stderr=True,
                                overwrite_output=True,
                            ),
                        )

                        if os.path.exists(compressed_file):
                            compressed_size = os.path.getsize(compressed_file)
                            if compressed_size <= (self.max_file_size * 1024 * 1024):
                                secure_delete_file(original_file)  # Remove original
                                return True, compressed_file, ""
                            else:
                                secure_delete_file(compressed_file)
                                return False, "", "Failed to compress to target size"
                    except Exception as e:
                        if compressed_file and os.path.exists(compressed_file):
                            secure_delete_file(compressed_file)
                        logger.error(f"Compression error: {str(e)}")
                        return False, "", f"Compression error: {str(e)}"

                return True, original_file, ""

        except Exception as e:
            # Clean up any leftover files
            if original_file and os.path.exists(original_file):
                secure_delete_file(original_file)
            if compressed_file and os.path.exists(compressed_file):
                secure_delete_file(compressed_file)
            logger.error(f"Download error: {str(e)}")
            return False, "", str(e)

    def is_supported_url(self, url: str) -> bool:
        """Check if URL is supported"""
        try:
            with yt_dlp.YoutubeDL() as ydl:
                # Try to extract info without downloading
                ie = ydl.extract_info(url, download=False, process=False)
                return ie is not None
        except:
            return False


class MessageManager:
    def __init__(self, message_duration: int, message_template: str):
        self.message_duration = message_duration
        self.message_template = message_template
        self.scheduled_deletions: Dict[int, asyncio.Task] = {}

    def format_archive_message(
        self, author: str, url: str, original_message: str
    ) -> str:
        return self.message_template.format(
            author=author, url=url, original_message=original_message
        )

    async def schedule_message_deletion(self, message_id: int, delete_func) -> None:
        if self.message_duration <= 0:
            return

        if message_id in self.scheduled_deletions:
            self.scheduled_deletions[message_id].cancel()

        async def delete_later():
            await asyncio.sleep(
                self.message_duration * 3600
            )  # Convert hours to seconds
            try:
                await delete_func()
            except Exception as e:
                logger.error(f"Failed to delete message {message_id}: {str(e)}")
            finally:
                self.scheduled_deletions.pop(message_id, None)

        self.scheduled_deletions[message_id] = asyncio.create_task(delete_later())

    def cancel_all_deletions(self):
        """Cancel all scheduled message deletions"""
        for task in self.scheduled_deletions.values():
            task.cancel()
        self.scheduled_deletions.clear()


def secure_delete_file(file_path: str, passes: int = 3) -> bool:
    """Securely delete a file by overwriting it multiple times before removal"""
    if not os.path.exists(file_path):
        return True

    try:
        file_size = os.path.getsize(file_path)
        for _ in range(passes):
            with open(file_path, "wb") as f:
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())

        try:
            os.remove(file_path)
        except OSError:
            pass

        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
        except OSError:
            pass

        return not os.path.exists(file_path)

    except Exception as e:
        logger.error(f"Error during secure delete of {file_path}: {str(e)}")
        # Attempt force delete as last resort
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass
        return not os.path.exists(file_path)


def cleanup_downloads(download_path: str) -> None:
    """Clean up the downloads directory without removing the directory itself"""
    try:
        if os.path.exists(download_path):
            # Delete all files in the directory
            for file_path in Path(download_path).glob("*"):
                if file_path.is_file():
                    secure_delete_file(str(file_path))
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
