from .overseerr import Overseerr

__red_end_user_data_statement__ = "This allows users to make requests to Overseerr and Admins can approve them."


async def setup(bot):
    await bot.add_cog(Overseerr(bot))