"""Module for tracking download and compression progress"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("ProgressTracker")

class ProgressTracker:
    """Tracks progress of downloads and compression operations"""

    def __init__(self):
        self._download_progress: Dict[str, Dict[str, Any]] = {}
        self._compression_progress: Dict[str, Dict[str, Any]] = {}

    def start_download(self, url: str) -> None:
        """Initialize progress tracking for a download"""
        self._download_progress[url] = {
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
            "last_update": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def update_download_progress(self, data: Dict[str, Any]) -> None:
        """Update download progress information"""
        try:
            # Get URL from info dict
            url = data.get("info_dict", {}).get("webpage_url", "unknown")
            if url not in self._download_progress:
                return

            if data["status"] == "downloading":
                self._download_progress[url].update({
                    "active": True,
                    "percent": float(data.get("_percent_str", "0").replace("%", "")),
                    "speed": data.get("_speed_str", "N/A"),
                    "eta": data.get("_eta_str", "N/A"),
                    "downloaded_bytes": data.get("downloaded_bytes", 0),
                    "total_bytes": data.get("total_bytes", 0) or data.get("total_bytes_estimate", 0),
                    "retries": data.get("retry_count", 0),
                    "fragment_count": data.get("fragment_count", 0),
                    "fragment_index": data.get("fragment_index", 0),
                    "video_title": data.get("info_dict", {}).get("title", "Unknown"),
                    "extractor": data.get("info_dict", {}).get("extractor", "Unknown"),
                    "format": data.get("info_dict", {}).get("format", "Unknown"),
                    "resolution": data.get("info_dict", {}).get("resolution", "Unknown"),
                    "fps": data.get("info_dict", {}).get("fps", "Unknown"),
                    "last_update": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                })

                logger.debug(
                    f"Download progress for {url}: "
                    f"{self._download_progress[url]['percent']}% at {self._download_progress[url]['speed']}, "
                    f"ETA: {self._download_progress[url]['eta']}"
                )

        except Exception as e:
            logger.error(f"Error updating download progress: {e}")

    def end_download(self, url: str) -> None:
        """Mark a download as completed"""
        if url in self._download_progress:
            self._download_progress[url]["active"] = False

    def start_compression(
        self,
        input_file: str,
        params: Dict[str, str],
        use_hardware: bool,
        duration: float,
        input_size: int,
        target_size: int
    ) -> None:
        """Initialize progress tracking for compression"""
        self._compression_progress[input_file] = {
            "active": True,
            "filename": input_file,
            "start_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "percent": 0,
            "elapsed_time": "0:00",
            "input_size": input_size,
            "current_size": 0,
            "target_size": target_size,
            "codec": params.get("c:v", "unknown"),
            "hardware_accel": use_hardware,
            "preset": params.get("preset", "unknown"),
            "crf": params.get("crf", "unknown"),
            "duration": duration,
            "bitrate": params.get("b:v", "unknown"),
            "audio_codec": params.get("c:a", "unknown"),
            "audio_bitrate": params.get("b:a", "unknown"),
            "last_update": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def update_compression_progress(
        self,
        input_file: str,
        progress: float,
        elapsed_time: str,
        current_size: int,
        current_time: float
    ) -> None:
        """Update compression progress information"""
        if input_file in self._compression_progress:
            self._compression_progress[input_file].update({
                "percent": progress,
                "elapsed_time": elapsed_time,
                "current_size": current_size,
                "current_time": current_time,
                "last_update": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            })

            logger.debug(
                f"Compression progress for {input_file}: "
                f"{progress:.1f}%, Size: {current_size}/{self._compression_progress[input_file]['target_size']} bytes"
            )

    def end_compression(self, input_file: str) -> None:
        """Mark a compression operation as completed"""
        if input_file in self._compression_progress:
            self._compression_progress[input_file]["active"] = False

    def get_download_progress(self, url: str) -> Optional[Dict[str, Any]]:
        """Get progress information for a download"""
        return self._download_progress.get(url)

    def get_compression_progress(self, input_file: str) -> Optional[Dict[str, Any]]:
        """Get progress information for a compression operation"""
        return self._compression_progress.get(input_file)

    def get_active_downloads(self) -> Dict[str, Dict[str, Any]]:
        """Get all active downloads"""
        return {
            url: progress
            for url, progress in self._download_progress.items()
            if progress.get("active", False)
        }

    def get_active_compressions(self) -> Dict[str, Dict[str, Any]]:
        """Get all active compression operations"""
        return {
            input_file: progress
            for input_file, progress in self._compression_progress.items()
            if progress.get("active", False)
        }

    def clear_progress(self) -> None:
        """Clear all progress tracking"""
        self._download_progress.clear()
        self._compression_progress.clear()
