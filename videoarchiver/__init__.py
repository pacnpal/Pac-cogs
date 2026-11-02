"""VideoArchiver cog for Red-DiscordBot"""

import logging
from redbot.core.bot import Red  # type: ignore

from .core.base import VideoArchiver
from .core.cleanup import cleanup_resources
from .utils.exceptions import (
    VideoArchiverError,
    CommandError,
    EventError,
    CogError,
    ErrorContext,
    ErrorSeverity,
    ProcessingError,
)

logger = logging.getLogger("VideoArchiver")

# Version information
__version__ = "1.0.0"
__author__ = "VideoArchiver Team"
__description__ = "Video archiving cog for Red-DiscordBot"


async def setup(bot: Red) -> None:
    """Load VideoArchiver with proper initialization."""
    try:
        # cog_load starts initialization in the background
        await bot.add_cog(VideoArchiver(bot))
        logger.info("VideoArchiver cog loaded successfully")

    except Exception as e:
        logger.error(f"Failed to load VideoArchiver: {str(e)}")
        raise


async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    try:
        # Remove cog and clean up resources
        if "VideoArchiver" in bot.cogs:
            cog = bot.get_cog("VideoArchiver")
            if cog:
                await cleanup_resources(cog)
            await bot.remove_cog("VideoArchiver")

        logger.info("VideoArchiver cog unloaded successfully")

    except Exception as e:
        logger.error(f"Error during teardown: {str(e)}")
        raise


__all__ = [
    "VideoArchiver",
    "VideoArchiverError",
    "CommandError",
    "EventError",
    "CogError",
    "ErrorContext",
    "ErrorSeverity",
    "ProcessingError",
    "setup",
    "teardown",
]
