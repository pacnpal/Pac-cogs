"""Overseerr cog for Red-DiscordBot"""
from redbot.core.bot import Red
from .overseerr import Overseerr

async def setup(bot: Red) -> None:
    """Load Overseerr cog."""
    cog = Overseerr(bot)
    # Add cog first
    await bot.add_cog(cog)
    # Then sync commands after cog is loaded
    if hasattr(bot, "tree"):
        try:
            # Only sync guild commands to avoid rate limits
            await bot.tree.sync(guild=None)
        except Exception as e:
            # Log error but don't fail cog load
            bot.log.error(f"Failed to sync commands: {str(e)}")

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    if hasattr(bot, "tree"):
        try:
            # Remove all commands from this cog
            for command in bot.tree.get_commands():
                bot.tree.remove_command(command.name)
            # Sync to remove commands from Discord
            await bot.tree.sync(guild=None)
        except Exception as e:
            # Log error but don't fail cog unload
            bot.log.error(f"Failed to cleanup commands: {str(e)}")
