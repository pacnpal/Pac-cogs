"""ThrillWiki cog for Red-DiscordBot"""
from redbot.core.bot import Red  # type: ignore

from .thrillwiki import ThrillWiki

__red_end_user_data_statement__ = "This cog does not store any user data."


async def setup(bot: Red) -> None:
    await bot.add_cog(ThrillWiki(bot))
