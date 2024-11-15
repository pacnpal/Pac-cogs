"""Overseerr cog for Red-DiscordBot"""
from redbot.core.bot import Red
from .overseerr import Overseerr

async def setup(bot: Red) -> None:
    """Load Overseerr cog."""
    cog = Overseerr(bot)
    await bot.add_cog(cog)

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    # Let Red handle command cleanup
    pass
