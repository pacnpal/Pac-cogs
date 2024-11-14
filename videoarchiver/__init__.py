"""VideoArchiver cog for Red-DiscordBot"""

from redbot.core.bot import Red
from redbot.core.utils import get_end_user_data_statement

from .video_archiver import VideoArchiver
from .ffmpeg.ffmpeg_manager import FFmpegManager
from .ffmpeg.exceptions import FFmpegError, GPUError, DownloadError

__red_end_user_data_statement__ = get_end_user_data_statement(__file__)

async def setup(bot: Red):
    await bot.add_cog(VideoArchiver(bot))
