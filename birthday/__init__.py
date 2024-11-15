"""Birthday cog for Red-DiscordBot"""
from redbot.core.bot import Red
import logging
import discord
from discord.app_commands.errors import CommandAlreadyRegistered
from .birthday import Birthday, birthday_context_menu

logger = logging.getLogger("Birthday")

async def setup(bot: Red) -> None:
    """Load Birthday cog."""
    try:
        cog = Birthday(bot)
        await bot.add_cog(cog)
        # Try to add context menu command, ignore if already registered
        try:
            bot.tree.add_command(birthday_context_menu)
        except CommandAlreadyRegistered:
            pass
        # Initialize scheduled tasks
        try:
            await cog.reload_scheduled_tasks()
        except Exception as e:
            logger.error(f"Failed to initialize scheduled tasks: {str(e)}")
            await bot.remove_cog(cog.__class__.__name__)
            raise
    except Exception as e:
        logger.error(f"Failed to load Birthday cog: {str(e)}")
        raise

async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    try:
        if "Birthday" in bot.cogs:
            await bot.remove_cog("Birthday")
        # Remove context menu command
        bot.tree.remove_command("Give Birthday Role", type=discord.AppCommandType.user)
    except Exception as e:
        logger.error(f"Error during teardown: {str(e)}")
        raise
