"""Shared progress tracking functionality"""

from typing import Dict, Any

# Global progress tracking
compression_progress: Dict[str, Dict[str, Any]] = {}
download_progress: Dict[str, Dict[str, Any]] = {}
processing_progress: Dict[str, Dict[str, Any]] = {}

def get_compression_progress(file_id: str) -> Dict[str, Any]:
    """Get compression progress for a file"""
    return compression_progress.get(file_id, {})

def update_compression_progress(file_id: str, progress_data: Dict[str, Any]) -> None:
    """Update compression progress for a file"""
    if file_id in compression_progress:
        compression_progress[file_id].update(progress_data)
    else:
        compression_progress[file_id] = progress_data

def clear_compression_progress(file_id: str) -> None:
    """Clear compression progress for a file"""
    compression_progress.pop(file_id, None)

def get_download_progress(url: str) -> Dict[str, Any]:
    """Get download progress for a URL"""
    return download_progress.get(url, {})

def update_download_progress(url: str, progress_data: Dict[str, Any]) -> None:
    """Update download progress for a URL"""
    if url in download_progress:
        download_progress[url].update(progress_data)
    else:
        download_progress[url] = progress_data

def clear_download_progress(url: str) -> None:
    """Clear download progress for a URL"""
    download_progress.pop(url, None)

def get_processing_progress(item_id: str) -> Dict[str, Any]:
    """Get processing progress for an item"""
    return processing_progress.get(item_id, {})

def update_processing_progress(item_id: str, progress_data: Dict[str, Any]) -> None:
    """Update processing progress for an item"""
    if item_id in processing_progress:
        processing_progress[item_id].update(progress_data)
    else:
        processing_progress[item_id] = progress_data

def clear_processing_progress(item_id: str) -> None:
    """Clear processing progress for an item"""
    processing_progress.pop(item_id, None)
