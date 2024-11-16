"""VideoArchiver cog for Red-DiscordBot"""
from redbot.core.bot import Red
import asyncio
import logging
from .core.base import VideoArchiver
from .exceptions import ProcessingError

logger = logging.getLogger("VideoArchiver")

async def setup(bot: Red) -> None:
    """Load VideoArchiver."""
    try:
        cog = VideoArchiver(bot)
        await bot.add_cog(cog)
    except Exception as e:
        logger.error(f"Failed to load VideoArchiver: {str(e)}")
        raise

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    try:
        if "VideoArchiver" in bot.cogs:
            await bot.remove_cog("VideoArchiver")
    except Exception as e:
        logger.error(f"Error during teardown: {str(e)}")
        raise
