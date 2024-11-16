"""Module for database-related commands"""

import discord
from redbot.core.commands import Context, hybrid_group, hybrid_command, guild_only, checks
from discord import app_commands
import logging
from ..response_handler import handle_response
from ...database.video_archive_db import VideoArchiveDB

logger = logging.getLogger("VideoArchiver")

def setup_database_commands(cog):
    """Set up database commands for the cog"""

    @cog.hybrid_group(name="archivedb", fallback="help")
    @guild_only()
    async def archivedb(ctx: Context):
        """Manage the video archive database."""
        if ctx.invoked_subcommand is None:
            await handle_response(
                ctx, "Use `/help archivedb` for a list of commands."
            )

    @archivedb.command(name="enable")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def enable_database(ctx: Context):
        """Enable the video archive database."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Check if database is already enabled
            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id, "use_database"
            )
            if current_setting:
                await handle_response(
                    ctx, "The video archive database is already enabled."
                )
                return

            # Initialize database
            cog.db = VideoArchiveDB(cog.data_path)

            # Update processor with database
            if cog.processor:
                cog.processor.db = cog.db
                if cog.processor.queue_handler:
                    cog.processor.queue_handler.db = cog.db

            # Update setting
            await cog.config_manager.update_setting(ctx.guild.id, "use_database", True)

            # Send success message
            await handle_response(ctx, "Video archive database has been enabled.")

        except Exception as e:
            logger.error(f"Error enabling database: {e}")
            await handle_response(
                ctx,
                "An error occurred while enabling the database. Please check the logs for details.",
            )

    @archivedb.command(name="disable")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def disable_database(ctx: Context):
        """Disable the video archive database."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id, "use_database"
            )
            if not current_setting:
                await handle_response(
                    ctx, "The video archive database is already disabled."
                )
                return

            # Remove database references
            cog.db = None
            cog.processor.db = None
            cog.processor.queue_handler.db = None

            await cog.config_manager.update_setting(
                ctx.guild.id, "use_database", False
            )
            await handle_response(
                ctx, "Video archive database has been disabled."
            )

        except Exception as e:
            logger.error(f"Error disabling database: {e}")
            await handle_response(
                ctx, "An error occurred while disabling the database."
            )

    @cog.hybrid_command()
    @guild_only()
    @app_commands.describe(url="The URL of the video to check")
    async def checkarchived(ctx: Context, url: str):
        """Check if a video URL has been archived and get its Discord link if it exists."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            if not cog.db:
                await handle_response(
                    ctx,
                    "The archive database is not enabled. Ask an admin to enable it with `/archivedb enable`",
                )
                return

            result = cog.db.get_archived_video(url)
            if result:
                discord_url, message_id, channel_id, guild_id = result
                embed = discord.Embed(
                    title="Video Found in Archive",
                    description=f"This video has been archived!\n\nOriginal URL: {url}",
                    color=discord.Color.green(),
                )
                embed.add_field(name="Archived Link", value=discord_url)
                await handle_response(ctx, embed=embed)
            else:
                embed = discord.Embed(
                    title="Video Not Found",
                    description="This video has not been archived yet.",
                    color=discord.Color.red(),
                )
                await handle_response(ctx, embed=embed)
        except Exception as e:
            logger.error(f"Error checking archived video: {e}")
            await handle_response(
                ctx, "An error occurred while checking the archive."
            )

    # Store commands in cog for access
    cog.archivedb = archivedb
    cog.enable_database = enable_database
    cog.disable_database = disable_database
    cog.checkarchived = checkarchived

    return archivedb
