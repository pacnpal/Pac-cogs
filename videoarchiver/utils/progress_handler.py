import logging
from datetime import datetime
from typing import Dict, Any, Optional, Callable
import os

logger = logging.getLogger("VideoArchiver")

class CancellableYTDLLogger:
    """Custom yt-dlp logger that can handle cancellation"""
    def __init__(self):
        self.cancelled = False

    def debug(self, msg):
        if self.cancelled:
            raise yt_dlp.utils.DownloadError("Download cancelled") # type: ignore
        logger.debug(msg)

    def warning(self, msg):
        if self.cancelled:
            raise yt_dlp.utils.DownloadError("Download cancelled") # type: ignore
        logger.warning(msg)

    def error(self, msg):
        if self.cancelled:
            raise yt_dlp.utils.DownloadError("Download cancelled") # type: ignore
        logger.error(msg)

class ProgressHandler:
    """Handles progress tracking and callbacks for video operations"""
    def __init__(self):
        self.progress_data: Dict[str, Dict[str, Any]] = {}

    def initialize_progress(self, url: str) -> None:
        """Initialize progress tracking for a URL"""
        self.progress_data[url] = {
            "active": True,
            "start_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "percent": 0,
            "speed": "N/A",
            "eta": "N/A",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "retries": 0,
            "fragment_count": 0,
            "fragment_index": 0,
            "video_title": "Unknown",
            "extractor": "Unknown",
            "format": "Unknown",
            "resolution": "Unknown",
            "fps": "Unknown",
        }

    def update(self, key: str, data: Dict[str, Any]) -> None:
        """Update progress data for a key"""
        if key in self.progress_data:
            self.progress_data[key].update(data)

    def complete(self, key: str) -> None:
        """Mark progress as complete for a key"""
        if key in self.progress_data:
            self.progress_data[key]["active"] = False
            self.progress_data[key]["percent"] = 100

    def get_progress(self, key: str) -> Optional[Dict[str, Any]]:
        """Get progress data for a key"""
        return self.progress_data.get(key)

    def handle_download_progress(self, d: Dict[str, Any], url: str, 
                               progress_callback: Optional[Callable[[float], None]] = None) -> None:
        """Handle download progress updates"""
        try:
            if d["status"] == "downloading":
                progress_data = {
                    "active": True,
                    "percent": float(d.get("_percent_str", "0").replace("%", "")),
                    "speed": d.get("_speed_str", "N/A"),
                    "eta": d.get("_eta_str", "N/A"),
                    "downloaded_bytes": d.get("downloaded_bytes", 0),
                    "total_bytes": d.get("total_bytes", 0) or d.get("total_bytes_estimate", 0),
                    "retries": d.get("retry_count", 0),
                    "fragment_count": d.get("fragment_count", 0),
                    "fragment_index": d.get("fragment_index", 0),
                    "video_title": d.get("info_dict", {}).get("title", "Unknown"),
                    "extractor": d.get("info_dict", {}).get("extractor", "Unknown"),
                    "format": d.get("info_dict", {}).get("format", "Unknown"),
                    "resolution": d.get("info_dict", {}).get("resolution", "Unknown"),
                    "fps": d.get("info_dict", {}).get("fps", "Unknown"),
                }
                self.update(url, progress_data)

                if progress_callback:
                    progress_callback(progress_data["percent"])

                logger.debug(
                    f"Download progress: {progress_data['percent']}% at {progress_data['speed']}, "
                    f"ETA: {progress_data['eta']}, Downloaded: {progress_data['downloaded_bytes']}/"
                    f"{progress_data['total_bytes']} bytes"
                )
            elif d["status"] == "finished":
                logger.info(f"Download completed: {d.get('filename', 'unknown')}")

        except Exception as e:
            logger.error(f"Error in progress handler: {str(e)}")

    def handle_compression_progress(self, input_file: str, current_time: float, duration: float,
                                  output_file: str, start_time: datetime,
                                  progress_callback: Optional[Callable[[float], None]] = None) -> None:
        """Handle compression progress updates"""
        try:
            if duration > 0:
                progress = min(100, (current_time / duration) * 100)
                elapsed = datetime.utcnow() - start_time

                self.update(input_file, {
                    "percent": progress,
                    "elapsed_time": str(elapsed).split(".")[0],
                    "current_size": os.path.getsize(output_file) if os.path.exists(output_file) else 0,
                    "current_time": current_time,
                })

                if progress_callback:
                    progress_callback(progress)

        except Exception as e:
            logger.error(f"Error updating compression progress: {str(e)}")
