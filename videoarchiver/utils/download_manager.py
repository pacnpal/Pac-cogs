"""Module for managing video downloads"""

import os
import shutil
import logging
import asyncio
import tempfile
import threading
import contextlib
import yt_dlp # type: ignore
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple, Callable, Any
from pathlib import Path

from ..utils.compression_manager import CompressionManager
from .file_operations import FileOperations
from .progress_tracker import ProgressTracker

progress_tracker = ProgressTracker()  # singleton shared with processor

logger = logging.getLogger("DownloadManager")


class CancellableYTDLLogger:
    """Custom yt-dlp logger that can be cancelled"""

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


class DownloadManager:
    """Manages video downloads and processing"""

    MAX_RETRIES = 5
    RETRY_DELAY = 10
    FILE_OP_RETRIES = 3
    FILE_OP_RETRY_DELAY = 1
    SHUTDOWN_TIMEOUT = 15  # seconds
    CANCEL_GRACE = 5  # seconds to wait for yt-dlp to stop after a cancel

    def __init__(
        self,
        download_path: str,
        video_format: str,
        max_quality: int,
        max_file_size: int,
        enabled_sites: Optional[List[str]] = None,
        concurrent_downloads: int = 2,
        ffmpeg_mgr=None,
    ):
        self.download_path = Path(download_path)
        self.download_path.mkdir(parents=True, exist_ok=True)
        os.chmod(str(self.download_path), 0o755)

        # Initialize components
        self.ffmpeg_mgr = ffmpeg_mgr
        self.file_ops = FileOperations()
        self.compression_manager = CompressionManager(ffmpeg_mgr, max_file_size)

        # Create thread pool
        self.download_pool = ThreadPoolExecutor(
            max_workers=max(1, min(3, concurrent_downloads)),
            thread_name_prefix="videoarchiver_download",
        )

        # Initialize state
        self._shutting_down = False
        self.ytdl_logger = CancellableYTDLLogger()

        # Configure yt-dlp options
        self.ydl_opts = self._configure_ydl_opts(
            video_format, max_quality, max_file_size, ffmpeg_mgr
        )

    def _configure_ydl_opts(
        self, video_format: str, max_quality: int, max_file_size: int, ffmpeg_mgr
    ) -> Dict[str, Any]:
        """Configure yt-dlp options"""
        q = max_quality
        formats = {  # pick streams that merge cleanly into the target container
            "webm": f"bestvideo[ext=webm][height<={q}]+bestaudio[ext=webm]/best[ext=webm][height<={q}]"
                    f"/bestvideo[height<={q}]+bestaudio/best[height<={q}]/best",
            "mp4": f"bv*[height<={q}][ext=mp4]+ba[ext=m4a]/b[height<={q}]/best",
        }
        return {
            "format": formats.get(video_format, f"bv*[height<={q}]+ba/b[height<={q}]/best"),  # mkv: anything
            "outtmpl": "%(title).200B [%(id)s].%(ext)s",  # bounded name, unique per video
            "merge_output_format": video_format,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "concurrent_fragment_downloads": 1,
            "retries": self.MAX_RETRIES,
            "fragment_retries": self.MAX_RETRIES,
            "file_access_retries": self.FILE_OP_RETRIES,
            "extractor_retries": self.MAX_RETRIES,
            "postprocessor_hooks": [self._check_file_size],
            "progress_hooks": [self._progress_hook],
            "ffmpeg_location": str(ffmpeg_mgr.get_ffmpeg_path()),
            "ffprobe_location": str(ffmpeg_mgr.get_ffprobe_path()),
            "paths": {"home": str(self.download_path)},
            "logger": self.ytdl_logger,
            "ignoreerrors": False,  # raise DownloadError so the real reason reaches the user
            "no_color": True,
            "geo_bypass": True,
            "socket_timeout": 60,
            "http_chunk_size": 1048576,
            "external_downloader_args": {"ffmpeg": ["-timeout", "60000000"]},
            "max_sleep_interval": 5,
            "sleep_interval": 1,
            # No "max_filesize": oversized downloads get compressed to max_file_size instead.
        }

    def _check_file_size(self, info: Dict[str, Any]) -> None:
        """Check if file size is within limits"""
        if info.get("filepath") and os.path.exists(info["filepath"]):
            try:
                size = os.path.getsize(info["filepath"])
                if size > self.compression_manager.max_file_size:
                    logger.info(
                        f"File exceeds size limit, will compress: {info['filepath']}"
                    )
            except OSError as e:
                logger.error(f"Error checking file size: {str(e)}")

    def _progress_hook(self, d: Dict[str, Any]) -> None:
        """Handle download progress"""
        if d["status"] == "finished":
            logger.info(f"Download completed: {d['filename']}")
        elif d["status"] == "downloading":
            try:
                info = d.get("info_dict") or {}
                url = info.get("original_url") or info.get("webpage_url")
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                if url:
                    progress_tracker.update_download_progress(url, {
                        "percent": downloaded / total * 100 if total else 0,
                        "downloaded_bytes": downloaded,
                        "total_bytes": total or 0,
                    })
            except Exception as e:
                logger.debug(f"Error logging progress: {str(e)}")

    async def cleanup(self) -> None:
        """Clean up resources"""
        self._shutting_down = True
        self.ytdl_logger.cancelled = True
        self.download_pool.shutdown(wait=False, cancel_futures=True)
        await self.compression_manager.cleanup()

    async def force_cleanup(self) -> None:
        """Force cleanup of all resources"""
        self._shutting_down = True
        self.ytdl_logger.cancelled = True
        self.download_pool.shutdown(wait=False, cancel_futures=True)
        await self.compression_manager.force_cleanup()

    async def download_video(
        self, url: str, progress_callback: Optional[Callable[[float], None]] = None
    ) -> Tuple[bool, str, str]:
        """Download and process a video"""
        if self._shutting_down:
            return False, "", "Downloader is shutting down"

        progress_tracker.update_download_progress(url, {"active": True, "percent": 0})

        try:
            # Download video
            success, file_path, error = await self._safe_download(
                url, progress_callback
            )
            if not success:
                return False, "", error

            # Verify and compress if needed
            return await self._process_downloaded_file(file_path, progress_callback)

        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return False, "", str(e)

        finally:
            progress_tracker.complete_download(url)

    async def _safe_download(
        self, url: str, progress_callback: Optional[Callable[[float], None]]
    ) -> Tuple[bool, str, str]:
        """Download with yt-dlp in the download pool (yt-dlp's own retries cover transient errors)"""
        # Private temp dir per download, so partial/fragment files vanish on any failure.
        tmp_dir = tempfile.mkdtemp(prefix="dl", dir=self.download_path)
        cancel = threading.Event()

        def check_cancel(_: Dict[str, Any]) -> None:
            if cancel.is_set() or self._shutting_down:
                raise yt_dlp.utils.DownloadCancelled()

        opts = {**self.ydl_opts, "paths": {"home": tmp_dir},
                "progress_hooks": [check_cancel, self._progress_hook],
                "postprocessor_hooks": [check_cancel, self._check_file_size]}
        if progress_callback:
            def report(d: Dict[str, Any]) -> None:
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if d.get("status") == "downloading" and total:
                    progress_callback(d.get("downloaded_bytes", 0) / total * 100)
            opts["progress_hooks"].append(report)

        def run() -> Optional[str]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            downloads = (info or {}).get("requested_downloads") or [{}]
            return downloads[0].get("filepath")  # final path, after any merge

        def discard(f: asyncio.Future) -> None:
            if not f.cancelled():
                f.exception()  # mark retrieved so asyncio doesn't log it
            shutil.rmtree(tmp_dir, ignore_errors=True)

        try:
            fut = asyncio.get_running_loop().run_in_executor(self.download_pool, run)
        except RuntimeError:  # pool already shut down
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        try:
            # shield: a cancel must not orphan the worker; it is stopped via `cancel` instead
            path = await asyncio.shield(fut)
            if not path or not os.path.isfile(path):
                return False, "", "Download finished but no file was produced"
            # Guilds share download_path: the temp dir's unique name keeps concurrent
            # downloads of the same video (and their _compressed.mp4) apart.
            stem, ext = os.path.splitext(os.path.basename(path))
            final_path = str(self.download_path / f"{stem}_{os.path.basename(tmp_dir)}{ext}")
            shutil.move(path, final_path)
            return True, final_path, ""
        except asyncio.CancelledError:
            cancel.set()  # check_cancel aborts yt-dlp at its next progress tick
            await asyncio.wait([fut], timeout=self.CANCEL_GRACE)
            raise
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"yt-dlp failed for {url}: {e}")
            return False, "", str(e)
        finally:
            if fut.done():
                discard(fut)
            else:  # worker still running: remove its dir only once it has stopped
                fut.add_done_callback(discard)

    async def _process_downloaded_file(
        self, file_path: str, progress_callback: Optional[Callable[[float], None]]
    ) -> Tuple[bool, str, str]:
        """Verify the download and compress it if it exceeds the size limit"""
        ffprobe = str(self.ffmpeg_mgr.get_ffprobe_path())
        if not await asyncio.to_thread(self.file_ops.verify_video_file, file_path, ffprobe):
            self._remove(file_path)
            return False, "", "Downloaded file is not a valid video"
        if os.path.getsize(file_path) <= self.compression_manager.max_file_size:
            return True, file_path, ""

        compressed = os.path.splitext(file_path)[0] + "_compressed.mp4"  # encoder emits h264/aac
        success = False
        try:
            success, error = await self.compression_manager.compress_video(
                file_path, compressed, progress_callback
            )
            return (True, compressed, "") if success else (False, "", error)
        finally:
            self._remove(file_path, *([] if success else [compressed]))

    @staticmethod
    def _remove(*paths: str) -> None:
        for path in paths:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
