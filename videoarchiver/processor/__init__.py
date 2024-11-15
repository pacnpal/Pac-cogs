"""Video processing module for VideoArchiver"""

from .core import VideoProcessor
from .reactions import REACTIONS
from .progress_tracker import ProgressTracker
from .message_handler import MessageHandler
from .queue_handler import QueueHandler

# Export public classes and constants
__all__ = [
    'VideoProcessor',
    'REACTIONS',
    'ProgressTracker',
    'MessageHandler',
    'QueueHandler'
]

# Create a shared progress tracker instance for module-level access
progress_tracker = ProgressTracker()

# Export progress tracking functions that wrap the instance methods
def update_download_progress(url, progress_data):
    """Update download progress for a specific URL"""
    progress_tracker.update_download_progress(url, progress_data)

def complete_download(url):
    """Mark a download as complete"""
    progress_tracker.complete_download(url)

def increment_download_retries(url):
    """Increment retry count for a download"""
    progress_tracker.increment_download_retries(url)

def get_download_progress(url=None):
    """Get download progress for a specific URL or all downloads"""
    return progress_tracker.get_download_progress(url)

def get_active_operations():
    """Get all active operations"""
    return progress_tracker.get_active_operations()
