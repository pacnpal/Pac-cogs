"""VideoArchiver cog for Red-DiscordBot"""

from redbot.core.bot import Red
from redbot.core.utils import get_end_user_data_statement

from videoarchiver.video_archiver import VideoArchiver
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager
from videoarchiver.ffmpeg.exceptions import FFmpegError, GPUError, DownloadError

__red_end_user_data_statement__ = get_end_user_data_statement(__file__)

async def setup(bot: Red):
    await bot.add_cog(VideoArchiver(bot))
