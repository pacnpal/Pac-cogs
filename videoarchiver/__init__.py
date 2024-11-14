import logging
from redbot.core.bot import Red
from redbot.core import errors
from .video_archiver import VideoArchiver

log = logging.getLogger("red.pacnpal.videoarchiver")

async def setup(bot: Red) -> None:
    """Load VideoArchiver cog with error handling."""
    try:
        cog = VideoArchiver(bot)
        await bot.add_cog(cog)
        log.info("VideoArchiver cog loaded successfully")
    except Exception as e:
        log.error(f"Failed to load VideoArchiver cog: {str(e)}")
        raise errors.CogLoadError("Failed to load VideoArchiver cog") from e
