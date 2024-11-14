from .video_archiver import VideoArchiver

async def setup(bot):
    await bot.add_cog(VideoArchiver(bot))
