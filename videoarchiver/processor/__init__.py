"""Video processing module for VideoArchiver"""

from typing import Dict, Any, Optional, Union, List, Tuple
import discord # type: ignore

try:
    # Try relative imports first
    from .core import VideoProcessor
    from .constants import (
        REACTIONS,
        ReactionType,
        ReactionEmojis,
        ProgressEmojis,
        get_reaction,
        get_progress_emoji,
    )
    from .url_extractor import (
        URLExtractor,
        URLMetadata,
        URLPattern,
        URLType,
        URLPatternManager,
        URLValidator,
        URLMetadataExtractor,
    )
    from .message_validator import (
        MessageValidator,
        ValidationContext,
        ValidationRule,
        ValidationResult,
        ValidationRuleManager,
        ValidationCache,
        ValidationStats,
        ValidationCacheEntry,
        ValidationError,
    )
    from .message_handler import MessageHandler
    from .queue_handler import QueueHandler
    from .queue_processor import QueueProcessor  # Added import
    from .reactions import (
        handle_archived_reaction,
        update_queue_position_reaction,
        update_progress_reaction,
        update_download_progress_reaction,
    )
    from ..utils.progress_tracker import progress_tracker
except ImportError:
    # Fall back to absolute imports if relative imports fail
    from videoarchiver.processor.core import VideoProcessor
    from videoarchiver.processor.constants import (
        REACTIONS,
        ReactionType,
        ReactionEmojis,
        ProgressEmojis,
        get_reaction,
        get_progress_emoji,
    )
    from videoarchiver.processor.url_extractor import (
        URLExtractor,
        URLMetadata,
        URLPattern,
        URLType,
        URLPatternManager,
        URLValidator,
        URLMetadataExtractor,
    )
    from videoarchiver.processor.message_validator import (
        MessageValidator,
        ValidationContext,
        ValidationRule,
        ValidationResult,
        ValidationRuleManager,
        ValidationCache,
        ValidationStats,
        ValidationCacheEntry,
        ValidationError,
    )
    from videoarchiver.processor.message_handler import MessageHandler
    from videoarchiver.processor.queue_handler import QueueHandler
    from videoarchiver.processor.queue_processor import QueueProcessor  # Added import
    from videoarchiver.processor.reactions import (
        handle_archived_reaction,
        update_queue_position_reaction,
        update_progress_reaction,
        update_download_progress_reaction,
    )
    from videoarchiver.utils.progress_tracker import progress_tracker

# Export public classes and constants
__all__ = [
    # Core components
    "VideoProcessor",
    "MessageHandler",
    "QueueHandler",
    "QueueProcessor",  # Added export
    # URL Extraction
    "URLExtractor",
    "URLMetadata",
    "URLPattern",
    "URLType",
    "URLPatternManager",
    "URLValidator",
    "URLMetadataExtractor",
    # Message Validation
    "MessageValidator",
    "ValidationContext",
    "ValidationRule",
    "ValidationResult",
    "ValidationRuleManager",
    "ValidationCache",
    "ValidationStats",
    "ValidationCacheEntry",
    "ValidationError",
    # Constants and enums
    "REACTIONS",
    "ReactionType",
    "ReactionEmojis",
    "ProgressEmojis",
    # Helper functions
    "get_reaction",
    "get_progress_emoji",
    "extract_urls",
    "validate_message",
    "update_download_progress",
    "complete_download",
    "increment_download_retries",
    "get_download_progress",
    "get_active_operations",
    "get_validation_stats",
    "clear_caches",
    # Reaction handlers
    "handle_archived_reaction",
    "update_queue_position_reaction",
    "update_progress_reaction",
    "update_download_progress_reaction",
]

# Version information
__version__ = "1.0.0"
__author__ = "VideoArchiver Team"
__description__ = "Video processing module for archiving Discord videos"

# Create shared instances for module-level access
url_extractor = URLExtractor()
message_validator = MessageValidator()


# URL extraction helper functions
async def extract_urls(
    message: discord.Message, enabled_sites: Optional[List[str]] = None
) -> List[URLMetadata]:
    """
    Extract video URLs from a Discord message.

    Args:
        message: Discord message to extract URLs from
        enabled_sites: Optional list of enabled site identifiers

    Returns:
        List of URLMetadata objects for extracted URLs
    """
    return await url_extractor.extract_urls(message, enabled_sites)


async def validate_message(
    message: discord.Message, settings: Dict[str, Any]
) -> Tuple[bool, Optional[str]]:
    """
    Validate a Discord message.

    Args:
        message: Discord message to validate
        settings: Guild settings dictionary

    Returns:
        Tuple of (is_valid, reason)

    Raises:
        ValidationError: If validation fails unexpectedly
    """
    return await message_validator.validate_message(message, settings)


# Progress tracking helper functions
def update_download_progress(url: str, progress_data: Dict[str, Any]) -> None:
    """
    Update download progress for a specific URL.

    Args:
        url: The URL being downloaded
        progress_data: Dictionary containing progress information
    """
    progress_tracker.update_download_progress(url, progress_data)


def complete_download(url: str) -> None:
    """
    Mark a download as complete.

    Args:
        url: The URL that completed downloading
    """
    progress_tracker.complete_download(url)


def increment_download_retries(url: str) -> None:
    """
    Increment retry count for a download.

    Args:
        url: The URL being retried
    """
    progress_tracker.increment_download_retries(url)


def get_download_progress(
    url: Optional[str] = None,
) -> Union[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """
    Get download progress for a specific URL or all downloads.

    Args:
        url: Optional URL to get progress for. If None, returns all download progress.

    Returns:
        Dictionary containing progress information for one or all downloads
    """
    return progress_tracker.get_download_progress(url)


def get_active_operations() -> Dict[str, Dict[str, Any]]:
    """
    Get all active operations.

    Returns:
        Dictionary containing information about all active operations
    """
    return progress_tracker.get_active_operations()


def get_validation_stats() -> ValidationStats:
    """
    Get message validation statistics.

    Returns:
        Dictionary containing validation statistics and rule information
    """
    return message_validator.get_stats()


def clear_caches(message_id: Optional[int] = None) -> None:
    """
    Clear URL and validation caches.

    Args:
        message_id: Optional message ID to clear caches for. If None, clears all caches.
    """
    url_extractor.clear_cache(message_id)
    message_validator.clear_cache(message_id)
