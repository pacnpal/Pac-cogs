"""Progress tracking for video downloads and compression"""

from typing import Dict, Any
from datetime import datetime

class ProgressTracker:
    """Tracks progress of video downloads and compression operations"""
    
    def __init__(self):
        self._download_progress: Dict[str, Dict[str, Any]] = {}
        self._compression_progress: Dict[str, Dict[str, Any]] = {}

    def update_download_progress(self, url: str, progress_data: Dict[str, Any]) -> None:
        """Update download progress for a specific URL"""
        if url not in self._download_progress:
            self._download_progress[url] = {
                'active': True,
                'start_time': datetime.utcnow().isoformat(),
                'retries': 0
            }
        
        self._download_progress[url].update(progress_data)

    def complete_download(self, url: str) -> None:
        """Mark a download as complete"""
        if url in self._download_progress:
            self._download_progress[url]['active'] = False
            self._download_progress[url]['completed_time'] = datetime.utcnow().isoformat()

    def increment_download_retries(self, url: str) -> None:
        """Increment retry count for a download"""
        if url in self._download_progress:
            self._download_progress[url]['retries'] = self._download_progress[url].get('retries', 0) + 1

    def update_compression_progress(self, file_id: str, progress_data: Dict[str, Any]) -> None:
        """Update compression progress for a specific file"""
        if file_id not in self._compression_progress:
            self._compression_progress[file_id] = {
                'active': True,
                'start_time': datetime.utcnow().isoformat()
            }
        
        self._compression_progress[file_id].update(progress_data)

    def complete_compression(self, file_id: str) -> None:
        """Mark a compression operation as complete"""
        if file_id in self._compression_progress:
            self._compression_progress[file_id]['active'] = False
            self._compression_progress[file_id]['completed_time'] = datetime.utcnow().isoformat()

    def get_download_progress(self, url: str = None) -> Dict[str, Any]:
        """Get download progress for a specific URL or all downloads"""
        if url:
            return self._download_progress.get(url, {})
        return self._download_progress

    def get_compression_progress(self, file_id: str = None) -> Dict[str, Any]:
        """Get compression progress for a specific file or all compressions"""
        if file_id:
            return self._compression_progress.get(file_id, {})
        return self._compression_progress

    def clear_completed(self) -> None:
        """Clear completed operations from tracking"""
        # Clear completed downloads
        self._download_progress = {
            url: data for url, data in self._download_progress.items()
            if data.get('active', False)
        }
        
        # Clear completed compressions
        self._compression_progress = {
            file_id: data for file_id, data in self._compression_progress.items()
            if data.get('active', False)
        }

    def get_active_operations(self) -> Dict[str, Dict[str, Any]]:
        """Get all active operations"""
        return {
            'downloads': {
                url: data for url, data in self._download_progress.items()
                if data.get('active', False)
            },
            'compressions': {
                file_id: data for file_id, data in self._compression_progress.items()
                if data.get('active', False)
            }
        }
