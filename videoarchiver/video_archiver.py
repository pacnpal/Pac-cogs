"""VideoArchiver cog for Red-DiscordBot"""

from .core import VideoArchiver

def setup(bot):
    """Load VideoArchiver cog."""
    bot.add_cog(VideoArchiver(bot))
