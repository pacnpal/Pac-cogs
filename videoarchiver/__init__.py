"""VideoArchiver cog for Red-DiscordBot"""
from redbot.core.bot import Red
from .video_archiver import VideoArchiver

async def setup(bot: Red) -> None:
    """Load VideoArchiver."""
    cog = VideoArchiver(bot)
    await bot.add_cog(cog)

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    # Let Red handle command cleanup
    pass
