"""Guild component management for VideoArchiver"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, Optional

try:
    # Try relative imports first
    from ..utils.download_core import DownloadCore
    from ..utils.message_manager import MessageManager
    from ..utils.file_ops import cleanup_downloads
    from ..utils.exceptions import VideoArchiverError as ProcessingError
except ImportError:
    # Fall back to absolute imports if relative imports fail
    from videoarchiver.utils.download_core import DownloadCore
    from videoarchiver.utils.message_manager import MessageManager
    from videoarchiver.utils.file_ops import cleanup_downloads
    from videoarchiver.utils.exceptions import VideoArchiverError as ProcessingError

if TYPE_CHECKING:
    try:
        from .base import VideoArchiver
    except ImportError:
        from videoarchiver.core.base import VideoArchiver

logger = logging.getLogger("VideoArchiver")


async def initialize_guild_components(cog: "VideoArchiver", guild_id: int) -> None:
    """Initialize or update components for a guild with error handling"""
    try:
        settings = await cog.config_manager.get_guild_settings(guild_id)

        # Ensure download directory exists and is clean
        cog.download_path.mkdir(parents=True, exist_ok=True)
        await cleanup_downloads(str(cog.download_path))

        # Clean up old components if they exist
        if guild_id in cog.components:
            old_components = cog.components[guild_id]
            if "message_manager" in old_components:
                await old_components["message_manager"].cancel_all_deletions()
            if "downloader" in old_components:
                old_components["downloader"] = None

        # Initialize new components with validated settings
        cog.components[guild_id] = {
            "downloader": DownloadCore(
                str(cog.download_path),
                settings["video_format"],
                settings["video_quality"],
                settings["max_file_size"],
                settings["enabled_sites"] if settings["enabled_sites"] else None,
                settings["concurrent_downloads"],
                ffmpeg_mgr=cog.ffmpeg_mgr,  # Use shared FFmpeg manager
            ),
            "message_manager": MessageManager(
                settings["message_duration"], settings["message_template"]
            ),
        }

        logger.info(f"Successfully initialized components for guild {guild_id}")

    except Exception as e:
        logger.error(f"Failed to initialize guild {guild_id}: {str(e)}")
        raise ProcessingError(f"Guild initialization failed: {str(e)}")


async def cleanup_guild_components(cog: "VideoArchiver", guild_id: int) -> None:
    """Clean up components for a specific guild"""
    try:
        if guild_id in cog.components:
            # Clean up components
            components = cog.components[guild_id]
            if "message_manager" in components:
                await components["message_manager"].cancel_all_deletions()
            if "downloader" in components:
                components["downloader"] = None
            if "ffmpeg_mgr" in components:
                components["ffmpeg_mgr"] = None

            # Remove guild components
            cog.components.pop(guild_id)

            logger.info(f"Cleaned up components for guild {guild_id}")
    except Exception as e:
        logger.error(f"Error cleaning up guild {guild_id}: {str(e)}")
        raise ProcessingError(f"Guild cleanup failed: {str(e)}")
