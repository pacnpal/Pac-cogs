"""VideoArchiver cog for Red-DiscordBot"""
from redbot.core.bot import Red
from .video_archiver import VideoArchiver

async def setup(bot: Red) -> None:
    """Load VideoArchiver."""
    # Load main cog first
    cog = VideoArchiver(bot)
    await bot.add_cog(cog)
    
    # Wait for initialization to complete
    await cog.ready.wait()
    
    # Only load commands if main cog initialized successfully
    if cog.ready.is_set():
        from .commands import VideoArchiverCommands
        commands_cog = VideoArchiverCommands(
            bot,
            cog.config_manager,
            cog.update_checker,
            cog.processor
        )
        await bot.add_cog(commands_cog)
