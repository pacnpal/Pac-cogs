"""VideoArchiver cog for Red-DiscordBot"""
from redbot.core.bot import Red
import asyncio
import logging
from .core.base import VideoArchiver
from .exceptions import ProcessingError

logger = logging.getLogger("VideoArchiver")

# Global lock to prevent multiple concurrent setup attempts
_setup_lock = asyncio.Lock()
_setup_in_progress = False

async def setup(bot: Red) -> None:
    """Load VideoArchiver."""
    global _setup_in_progress

    # Use lock to prevent multiple concurrent setup attempts
    async with _setup_lock:
        try:
            # Check if setup is already in progress
            if _setup_in_progress:
                logger.warning("VideoArchiver setup already in progress, skipping")
                return

            # Check if cog is already loaded
            if "VideoArchiver" in bot.cogs:
                logger.warning("VideoArchiver already loaded, skipping")
                return

            _setup_in_progress = True
            
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
        finally:
            _setup_in_progress = False

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    try:
        if "VideoArchiver" in bot.cogs:
            await bot.remove_cog("VideoArchiver")
    except Exception as e:
        logger.error(f"Error during teardown: {str(e)}")
        raise
