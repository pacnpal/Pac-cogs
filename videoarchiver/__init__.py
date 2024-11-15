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
        # Load main cog
        cog = VideoArchiver(bot)
        await bot.add_cog(cog)
        
        # Wait for initialization to complete with timeout
        try:
            await asyncio.wait_for(cog.ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            logger.error("VideoArchiver initialization timed out")
            await bot.remove_cog(cog.__class__.__name__)
            raise ProcessingError("Initialization timed out")
        
        if not cog.ready.is_set():
            logger.error("VideoArchiver failed to initialize")
            await bot.remove_cog(cog.__class__.__name__)
            raise ProcessingError("Initialization failed")
            
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
