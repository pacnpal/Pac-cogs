"""Birthday cog for Red-DiscordBot"""
from redbot.core.bot import Red
import logging
from .birthday import Birthday

logger = logging.getLogger("Birthday")

async def setup(bot: Red) -> None:
    """Load Birthday cog."""
    try:
        cog = Birthday(bot)
        await bot.add_cog(cog)
        # Initialize scheduled tasks
        try:
            await cog.reload_scheduled_tasks()
        except Exception as e:
            logger.error(f"Failed to initialize scheduled tasks: {str(e)}")
            await bot.remove_cog(cog.__class__.__name__)
            raise
    except Exception as e:
        logger.error(f"Failed to load Birthday cog: {str(e)}")
        raise

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    try:
        if "Birthday" in bot.cogs:
            await bot.remove_cog("Birthday")
    except Exception as e:
        logger.error(f"Error during teardown: {str(e)}")
        raise
