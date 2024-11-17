"""Progress tracking module."""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum, auto

logger = logging.getLogger(__name__)

class ProgressStatus(Enum):
    """Status of a progress operation"""
    PENDING = auto()
    ACTIVE = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()

class ProgressTracker:
    """Progress tracker for downloads and compressions."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._download_progress: Dict[str, Dict[str, Any]] = {}
            self._compression_progress: Dict[str, Dict[str, Any]] = {}
            self._initialized = True

    def update_download_progress(self, url: str, data: Dict[str, Any]) -> None:
        """Update progress for a download."""
        if url not in self._download_progress:
            self._download_progress[url] = {
                'active': True,
                'start_time': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                'percent': 0,
                'retries': 0
            }
        self._download_progress[url].update(data)
        self._download_progress[url]['last_update'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"Download progress for {url}: {self._download_progress[url].get('percent', 0)}%")

    def increment_download_retries(self, url: str) -> None:
        """Increment retry count for a download."""
        if url in self._download_progress:
            self._download_progress[url]['retries'] = self._download_progress[url].get('retries', 0) + 1
            logger.debug(f"Incremented retries for {url} to {self._download_progress[url]['retries']}")

    def get_download_progress(self, url: Optional[str] = None) -> Dict[str, Any]:
        """Get progress for a download."""
        if url is None:
            return self._download_progress
        return self._download_progress.get(url, {})

    def update_compression_progress(self, file_path: str, data: Dict[str, Any]) -> None:
        """Update progress for a compression."""
        if file_path not in self._compression_progress:
            self._compression_progress[file_path] = {
                'active': True,
                'start_time': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                'percent': 0
            }
        self._compression_progress[file_path].update(data)
        self._compression_progress[file_path]['last_update'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"Compression progress for {file_path}: {self._compression_progress[file_path].get('percent', 0)}%")

    def get_compression_progress(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """Get progress for a compression."""
        if file_path is None:
            return self._compression_progress
        return self._compression_progress.get(file_path, {})

    def complete_download(self, url: str) -> None:
        """Mark download as complete."""
        if url in self._download_progress:
            self._download_progress[url]['active'] = False
            logger.info(f"Download completed for {url}")

    def complete_compression(self, file_path: str) -> None:
        """Mark compression as complete."""
        if file_path in self._compression_progress:
            self._compression_progress[file_path]['active'] = False
            logger.info(f"Compression completed for {file_path}")

    def clear(self) -> None:
        """Clear all progress data."""
        self._download_progress.clear()
        self._compression_progress.clear()
        logger.info("Progress data cleared")

    def is_healthy(self) -> bool:
        """Check if tracker is healthy."""
        return True  # Basic health check, can be expanded if needed
