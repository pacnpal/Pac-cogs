"""Overseerr cog for Red-DiscordBot"""
from redbot.core.bot import Red # type: ignore
import logging
from .overseerr import Overseerr

logger = logging.getLogger("Overseerr")

async def setup(bot: Red) -> None:
    """Load Overseerr cog."""
    try:
        cog = Overseerr(bot)
        await bot.add_cog(cog)
    except Exception as e:
        logger.error(f"Failed to load Overseerr cog: {str(e)}")
        raise

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    try:
        if "Overseerr" in bot.cogs:
            await bot.remove_cog("Overseerr")
    except Exception as e:
        logger.error(f"Error during teardown: {str(e)}")
        raise
