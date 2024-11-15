"""VideoArchiver cog for Red-DiscordBot"""
from redbot.core.bot import Red
from .video_archiver import VideoArchiver

async def setup(bot: Red) -> None:
    """Load VideoArchiver."""
    cog = VideoArchiver(bot)
    await bot.add_cog(cog)
    # Sync commands with Discord
    if not hasattr(bot, "tree"):
        return
    await bot.tree.sync()
