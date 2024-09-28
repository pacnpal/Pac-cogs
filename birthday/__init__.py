from .birthday import Birthday

__red_end_user_data_statement__ = "This allows users with the set roles to give the birthday role to users until the end of the day."


def setup(bot):
    await bot.add_cog(Birthday(bot))