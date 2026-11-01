"""Birthday cog for Red-DiscordBot."""
from redbot.core.bot import Red  # type: ignore

from .birthday import Birthday

__red_end_user_data_statement__ = (
    "This cog stores the IDs of members who currently have the birthday role and when it "
    "should be removed. That entry is deleted when the role comes off or on a data deletion request."
)


async def setup(bot: Red) -> None:
    await bot.add_cog(Birthday(bot))
