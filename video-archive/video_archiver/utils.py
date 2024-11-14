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

# Global thread pool for concurrent downloads
download_pool = ThreadPoolExecutor(max_workers=3)

class VideoDownloader:
    def __init__(self, download_path: str, video_format: str, max_quality: int, max_file_size: int, enabled_sites: Optional[List[str]] = None):
        self.download_path = download_path
        self.video_format = video_format
        self.max_quality = max_quality
        self.max_file_size = max_file_size
        self.enabled_sites = enabled_sites
        self.url_patterns = self._get_url_patterns()

        # Configure yt-dlp options
        self.ydl_opts = {
            'format': f'bestvideo[height<={max_quality}]+bestaudio/best[height<={max_quality}]',
            'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s'),
            'merge_output_format': video_format,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'concurrent_fragment_downloads': 3,
            'postprocessor_hooks': [self._check_file_size],
            'progress_hooks': [self._progress_hook],
            'ffmpeg_location': ffmpeg_mgr.get_ffmpeg_path(),
        }

    def _get_url_patterns(self) -> List[str]:
        """Get URL patterns for supported sites"""
        patterns = []
        with yt_dlp.YoutubeDL() as ydl:
            for extractor in ydl._ies:
                if hasattr(extractor, '_VALID_URL') and extractor._VALID_URL:
                    if not self.enabled_sites or any(site.lower() in extractor.IE_NAME.lower() for site in self.enabled_sites):
                        patterns.append(extractor._VALID_URL)
        return patterns

    def _check_file_size(self, info):
        """Check if file size is within limits"""
        if info.get('filepath') and os.path.exists(info['filepath']):
            size = os.path.getsize(info['filepath'])
            if size > (self.max_file_size * 1024 * 1024):
                logger.info(f"File exceeds size limit, will compress: {info['filepath']}")

    def _progress_hook(self, d):
        """Handle download progress"""
        if d['status'] == 'finished':
            logger.info(f"Download completed: {d['filename']}")

    async def download_video(self, url: str) -> Tuple[bool, str, str]:
        """Download and process a video"""
        try:
            # Configure yt-dlp for this download
            ydl_opts = self.ydl_opts.copy()
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Run download in executor to prevent blocking
                info = await asyncio.get_event_loop().run_in_executor(
                    download_pool, lambda: ydl.extract_info(url, download=True)
                )

                if info is None:
                    return False, "", "Failed to extract video information"

                file_path = os.path.join(self.download_path, ydl.prepare_filename(info))

                if not os.path.exists(file_path):
                    return False, "", "Download completed but file not found"

                # Check file size and compress if needed
                file_size = os.path.getsize(file_path)
                if file_size > (self.max_file_size * 1024 * 1024):
                    logger.info(f"Compressing video: {file_path}")
                    try:
                        # Get optimal compression parameters
                        params = ffmpeg_mgr.get_compression_params(file_path, self.max_file_size)
                        output_path = file_path + ".compressed." + self.video_format

                        # Configure ffmpeg with optimal parameters
                        stream = ffmpeg.input(file_path)
                        stream = ffmpeg.output(stream, output_path, **params)

                        # Run compression in executor
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: ffmpeg.run(
                                stream,
                                capture_stdout=True,
                                capture_stderr=True,
                                overwrite_output=True,
                            ),
                        )

                        if os.path.exists(output_path):
                            compressed_size = os.path.getsize(output_path)
                            if compressed_size <= (self.max_file_size * 1024 * 1024):
                                os.remove(file_path)  # Remove original
                                return True, output_path, ""
                            else:
                                os.remove(output_path)
                                return False, "", "Failed to compress to target size"
                    except Exception as e:
                        logger.error(f"Compression error: {str(e)}")
                        return False, "", f"Compression error: {str(e)}"

                return True, file_path, ""

        except Exception as e:
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

    def format_archive_message(self, author: str, url: str, original_message: str) -> str:
        return self.message_template.format(
            author=author, url=url, original_message=original_message
        )

    async def schedule_message_deletion(self, message_id: int, delete_func) -> None:
        if self.message_duration <= 0:
            return

        if message_id in self.scheduled_deletions:
            self.scheduled_deletions[message_id].cancel()

        async def delete_later():
            await asyncio.sleep(self.message_duration * 3600)  # Convert hours to seconds
            try:
                await delete_func()
            except Exception as e:
                logger.error(f"Failed to delete message {message_id}: {str(e)}")
            finally:
                self.scheduled_deletions.pop(message_id, None)

        self.scheduled_deletions[message_id] = asyncio.create_task(delete_later())


def secure_delete_file(file_path: str, passes: int = 3) -> bool:
    if not os.path.exists(file_path):
        return True

    try:
        file_size = os.path.getsize(file_path)
        for _ in range(passes):
            with open(file_path, "wb") as f:
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())

        os.remove(file_path)

        if os.path.exists(file_path) or Path(file_path).exists():
            os.unlink(file_path)

        return not (os.path.exists(file_path) or Path(file_path).exists())

    except Exception as e:
        logger.error(f"Error during secure delete: {str(e)}")
        return False


def cleanup_downloads(download_path: str) -> None:
    try:
        if os.path.exists(download_path):
            for file_path in Path(download_path).glob("*"):
                secure_delete_file(str(file_path))

            shutil.rmtree(download_path, ignore_errors=True)
            Path(download_path).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
