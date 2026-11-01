"""Provenance cog for Red-DiscordBot"""
from redbot.core.bot import Red # type: ignore
import logging
from .provenance import Provenance

logger = logging.getLogger("red.provenance")

async def setup(bot: Red) -> None:
    """Load Provenance cog."""
    try:
        cog = Provenance(bot)
        await bot.add_cog(cog)
    except Exception as e:
        logger.error(f"Failed to load Provenance cog: {str(e)}")
        raise

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    try:
        if "Provenance" in bot.cogs:
            await bot.remove_cog("Provenance")
    except Exception as e:
        logger.error(f"Error during teardown: {str(e)}")
        raise
