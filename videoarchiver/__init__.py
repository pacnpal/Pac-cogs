"""VideoArchiver cog for Red-DiscordBot"""
from redbot.core.bot import Red
from .video_archiver import VideoArchiver
from .commands import VideoArchiverCommands

async def setup(bot: Red) -> None:
    """Load VideoArchiver."""
    cog = VideoArchiver(bot)
    await bot.add_cog(cog)
    # Add commands from VideoArchiverCommands
    commands_cog = VideoArchiverCommands(bot, cog.config_manager, cog.update_checker, cog.processor)
    await bot.add_cog(commands_cog)
