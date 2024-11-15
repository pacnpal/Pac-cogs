"""VideoArchiver cog for Red-DiscordBot"""
from redbot.core.bot import Red
import asyncio
import logging
from .video_archiver import VideoArchiver
from .exceptions import ProcessingError

logger = logging.getLogger("VideoArchiver")

async def setup(bot: Red) -> None:
    """Load VideoArchiver."""
    try:
        # Load main cog first
        cog = VideoArchiver(bot)
        await bot.add_cog(cog)
        
        # Wait for initialization to complete with timeout
        try:
            await asyncio.wait_for(cog.ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            logger.error("VideoArchiver initialization timed out")
            await bot.remove_cog(cog.__class__.__name__)
            raise ProcessingError("Initialization timed out")
        
        # Only load commands if main cog initialized successfully
        if cog.ready.is_set():
            try:
                from .commands import VideoArchiverCommands
                commands_cog = VideoArchiverCommands(
                    bot,
                    cog.config_manager,
                    cog.update_checker,
                    cog.processor
                )
                await bot.add_cog(commands_cog)
            except Exception as e:
                logger.error(f"Failed to load commands cog: {str(e)}")
                # Clean up main cog if commands fail to load
                await bot.remove_cog(cog.__class__.__name__)
                raise
        else:
            logger.error("VideoArchiver failed to initialize")
            await bot.remove_cog(cog.__class__.__name__)
            raise ProcessingError("Initialization failed")
            
    except Exception as e:
        logger.error(f"Failed to load VideoArchiver: {str(e)}")
        raise

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    try:
        # Remove commands cog first
        if "VideoArchiverCommands" in bot.cogs:
            await bot.remove_cog("VideoArchiverCommands")
        
        # Then remove main cog
        if "VideoArchiver" in bot.cogs:
            await bot.remove_cog("VideoArchiver")
    except Exception as e:
        logger.error(f"Error during teardown: {str(e)}")
        raise
