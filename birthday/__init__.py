"""Birthday cog for Red-DiscordBot"""
from redbot.core.bot import Red
from .birthday import Birthday

async def setup(bot: Red) -> None:
    """Load Birthday cog."""
    cog = Birthday(bot)
    await bot.add_cog(cog)

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    # Let Red handle command cleanup
    pass
