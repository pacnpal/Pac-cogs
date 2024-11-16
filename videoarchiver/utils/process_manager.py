"""Process management and cleanup utilities"""

import asyncio
import logging
import subprocess
from typing import Set, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("VideoArchiver")

class ProcessManager:
    """Manages processes and resources for video operations"""

    def __init__(self, concurrent_downloads: int = 2):
        self._active_processes: Set[subprocess.Popen] = set()
        self._processes_lock = asyncio.Lock()
        self._shutting_down = False
        
        # Create thread pool with proper naming
        self.download_pool = ThreadPoolExecutor(
            max_workers=max(1, min(3, concurrent_downloads)),
            thread_name_prefix="videoarchiver_download"
        )

        # Track active downloads
        self.active_downloads: Dict[str, Dict[str, Any]] = {}
        self._downloads_lock = asyncio.Lock()

    async def cleanup(self) -> None:
        """Clean up resources with proper shutdown"""
        self._shutting_down = True

        try:
            # Kill any active processes
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
            logger.error(f"Error during process manager cleanup: {e}")
        finally:
            self._shutting_down = False

    async def force_cleanup(self) -> None:
        """Force cleanup of all resources"""
        try:
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

    async def track_download(self, url: str, file_path: str) -> None:
        """Track a new download"""
        async with self._downloads_lock:
            self.active_downloads[url] = {
                "file_path": file_path,
                "start_time": datetime.utcnow(),
            }

    async def untrack_download(self, url: str) -> None:
        """Remove download from tracking"""
        async with self._downloads_lock:
            self.active_downloads.pop(url, None)

    async def track_process(self, process: subprocess.Popen) -> None:
        """Track a new process"""
        async with self._processes_lock:
            self._active_processes.add(process)

    async def untrack_process(self, process: subprocess.Popen) -> None:
        """Remove process from tracking"""
        async with self._processes_lock:
            self._active_processes.discard(process)

    @property
    def is_shutting_down(self) -> bool:
        """Check if manager is shutting down"""
        return self._shutting_down

    def get_active_downloads(self) -> Dict[str, Dict[str, Any]]:
        """Get current active downloads"""
        return self.acti