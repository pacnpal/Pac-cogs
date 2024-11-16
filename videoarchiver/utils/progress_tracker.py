"""Progress tracking module."""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class ProgressTracker:
    """Progress tracker singleton."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._data: Dict[str, Dict[str, Any]] = {}
            self._initialized = True

    def update(self, key: str, data: Dict[str, Any]) -> None:
        """Update progress for a key."""
        if key not in self._data:
            self._data[key] = {
                'active': True,
                'start_time': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                'percent': 0
            }
        self._data[key].update(data)
        self._data[key]['last_update'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"Progress for {key}: {self._data[key].get('percent', 0)}%")

    def get(self, key: Optional[str] = None) -> Dict[str, Any]:
        """Get progress for a key."""
        if key is None:
            return self._data
        return self._data.get(key, {})

    def complete(self, key: str) -> None:
        """Mark progress as complete."""
        if key in self._data:
            self._data[key]['active'] = False
            logger.info(f"Operation completed for {key}")

    def clear(self) -> None:
        """Clear all progress data."""
        self._data.clear()
        logger.info("Progress data cleared")

_tracker = ProgressTracker()

    def get_compression(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """Get compression progress."""
        if file_path is None:
            return self._compressions
        return self._compressions.get(file_path, {})

    def complete_download(self, url: str) -> None:
        """Mark download as complete."""
        if url in self._downloads:
            self._downloads[url]['active'] = False
            logger.info(f"Download completed for {url}")

    def complete_compression(self, file_path: str) -> None:
        """Mark compression as complete."""
        if file_path in self._compressions:
            self._compressions[file_path]['active'] = False
            logger.info(f"Compression completed for {file_path}")

    def clear(self) -> None:
        """Clear all progress data."""
        self._downloads.clear()
        self._compressions.clear()
        logger.info("Progress data cleared")

# Global instance
_tracker = ProgressTrack

# Global instance
_tracker = ProgressTracker()

def get_tracker() -> Progre
        """Clear all progress tracking"""
        self._download_progress.clear()
        self._compression_progress.clear()
        logger.info("Cleared all progress tracking data")

# Create singleton instance
progress_tracker = ProgressTracker()

def get_progress_tracker() -> ProgressTracker:
  
    def mark_compression_complete(self, file_path: str) -> None:
        """Mark a compression operation as complete"""
        if file_path in self._compression_progress:
            self._compression_progress[file_path]['active'] = False
            logger.info(f"Compression completed for {file_path}")

    def clear_progress(self) -> None:
        """Clear all progress tracking"""
        self._download_progress.clear()
        self._compression_progress.clear()
        logger.info("Cleared all progress tracking data")

# Create singleton instance
progress_tracker = ProgressTracker()

# Export the singleton instance
def get_progress_tracker() -> ProgressTracker:
    
        
        Args:
            data: Dictionary containing download progress data
        """
        try:
            info_dict = data.get("info_dict", {})
            url = info_dict.get("webpage_url")
            if not url or url not in self._download_progress:
                return

            if data.get("status") == "downloading":
                percent_str = data.get("_percent_str", "0").replace("%", "")
                try:
                    percent = float(percent_str)
                except ValueError:
                    percent = 0.0

                total_bytes = (
                    data.get("total_bytes", 0) or 
                    data.get("total_bytes_estimate", 0)
                )

                self._download_progress[url].update({
                    "active": True,
                    "percent": percent,
                    "speed": data.get("_speed_str", "N/A"),
                    "eta": data.get("_eta_str", "N/A"),
                    "downloaded_bytes": data.get("downloaded_bytes", 0),
                    "total_bytes": total_bytes,
                    "retries": data.get("retry_count", 0),
                    "fragment_count": data.get("fragment_count", 0),
                    "fragment_index": data.get("fragment_index", 0),
                    "video_title": info_dict.get("title", "Unknown"),
                    "extractor": info_dict.get("extractor", "Unknown"),
                    "format": info_dict.get("format", "Unknown"),
                    "resolution": info_dict.get("resolution", "Unknown"),
                    "fps": info_dict.get("fps", "Unknown"),
                    "last_update": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                })

                logger.debug(
                    f"Download progress for {url}: "
                    f"{percent:.1f}% at {self._download_progress[url]['speed']}, "
                    f"ETA: {self._download_progress[url]['eta']}"
                )

        except Exception as e:
            logger.error(f"Error updating download progress: {e}", exc_info=True)

    def end_download(self, url: str, status: ProgressStatus = ProgressStatus.COMPLETED) -> None:
        """
        Mark a download as completed.
        
        Args:
            url: The URL being downloaded
            status: The final status of the download
        """
        if url in self._download_progress:
            self._download_progress[url]["active"] = False
            logger.info(f"Download {status.value} for {url}")

    def start_compression(self, params: CompressionParams) -> None:
        """
        Initialize progress tracking for compression.
        
        Args:
            params: Compression parameters
        """
        current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self._compression_progress[params.input_file] = CompressionProgress(
            active=True,
            filename=params.input_file,
            start_time=current_time,
            percent=0.0,
            elapsed_time="0:00",
            input_size=params.input_size,
            current_size=0,
            target_size=params.target_size,
            codec=params.codec_params.get("c:v", "unknown"),
            hardware_accel=params.use_hardware,
            preset=params.codec_params.get("preset", "unknown"),
            crf=params.codec_params.get("crf", "unknown"),
            duration=params.duration,
            bitrate=params.codec_params.get("b:v", "unknown"),
            audio_codec=params.codec_params.get("c:a", "unknown"),
            audio_bitrate=params.codec_params.get("b:a", "unknown"),
            last_update=current_time,
            current_time=None
        )

    def update_compression_progress(
        self,
        input_file: str,
        progress: float,
        elapsed_time: str,
        current_size: int,
        current_time: float
    ) -> None:
        """
        Update compression progress information.
        
        Args:
            input_file: The input file being compressed
            progress: Current progress percentage (0-100)
            elapsed_time: Time elapsed as string
            current_size: Current file size in bytes
            current_time: Current timestamp in seconds
        """
        if input_file in self._compression_progress:
            self._compression_progress[input_file].update({
                "percent": max(0.0, min(100.0, progress)),
                "elapsed_time": elapsed_time,
                "current_size": current_size,
                "current_time": current_time,
                "last_update": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            })

            logger.debug(
                f"Compression progress for {input_file}: "
                f"{progress:.1f}%, Size: {current_size}/{self._compression_progress[input_file]['target_size']} bytes"
            )

    def end_compression(
        self,
        input_file: str,
        status: ProgressStatus = ProgressStatus.COMPLETED
    ) -> None:
        """
        Mark a compression operation as completed.
        
        Args:
            input_file: The input file being compressed
            status: The final status of the compression
        """
        if input_file in self._compression_progress:
            self._compression_progress[input_file]["active"] = False
            logger.info(f"Compression {status.value} for {input_file}")

    def get_download_progress(self, url: Optional[str] = None) -> Optional[DownloadProgress]:
        """
        Get progress information for a download.
        
        Args:
            url: Optional URL to get progress for. If None, returns all progress.
            
        Returns:
            Progress information for the specified download or None if not found
        """
        if url is None:
            return self._download_progress
        return self._download_progress.get(url)

    def get_compression_progress(
        self,
        input_file: Optional[str] = None
    ) -> Optional[CompressionProgress]:
        """
        Get progress information for a compression operation.
        
        Args:
            input_file: Optional file to get progress for. If None, returns all progress.
            
        Returns:
            Progress information for the specified compression or None if not found
        """
        if input_file is None:
            return self._compression_progress
        return self._compression_progress.get(input_file)

    def get_active_downloads(self) -> Dict[str, DownloadProgress]:
        """
        Get all active downloads.
        
        Returns:
            Dictionary of active downloads and their progress
        """
        return {
            url: progress
            for url, progress in self._download_progress.items()
            if progress.get("active", False)
        }

    def get_active_compressions(self) -> Dict[str, CompressionProgress]:
        """
        Get all active compression operations.
        
        Returns:
            Dictionary of active compressions and their progress
        """
        return {
            input_file: progress
            for input_file, progress in self._compression_progress.items()
            if progress.get("active", False)
        }

    def clear_progress(self) -> None:
        """Clear all progress tracking"""
        self._download_progress.clear()
        self._compression_progress.clear()
        logger.info("Cleared