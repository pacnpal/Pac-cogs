"""Command handlers for VideoArchiver"""

import logging
import discord
import traceback
from redbot.core import commands, checks
from discord import app_commands
from typing import TYPE_CHECKING

from ..utils.exceptions import (
    ConfigurationError as ConfigError,
    VideoArchiverError as ProcessingError,
)
from ..database.video_archive_db import VideoArchiveDB

if TYPE_CHECKING:
    from .base import VideoArchiver

logger = logging.getLogger("VideoArchiver")

def setup_commands(cog: "VideoArchiver") -> None:
    """Set up command handlers for the cog"""

    @cog.hybrid_group(name="archivedb", fallback="help")
    @commands.guild_only()
    async def archivedb(ctx: commands.Context):
        """Manage the video archive database."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @archivedb.command(name="enable")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def enable_database(ctx: commands.Context):
        """Enable the video archive database."""
        try:
            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id, "use_database"
            )
            if current_setting:
                await ctx.send("The video archive database is already enabled.")
                return

            # Initialize database if it's being enabled
            cog.db = VideoArchiveDB(cog.data_path)
            # Update processor with database
            cog.processor.db = cog.db
            cog.processor.queue_handler.db = cog.db

            await cog.config_manager.update_setting(ctx.guild.id, "use_database", True)
            await ctx.send("Video archive database has been enabled.")

        except Exception as e:
            logger.error(f"Error enabling database: {e}")
            await ctx.send("An error occurred while enabling the database.")

    @archivedb.command(name="disable")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def disable_database(ctx: commands.Context):
        """Disable the video archive database."""
        try:
            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id, "use_database"
            )
            if not current_setting:
                await ctx.send("The video archive database is already disabled.")
                return

            # Remove database references
            cog.db = None
            cog.processor.db = None
            cog.processor.queue_handler.db = None

            await cog.config_manager.update_setting(ctx.guild.id, "use_database", False)
            await ctx.send("Video archive database has been disabled.")

        except Exception as e:
            logger.error(f"Error disabling database: {e}")
            await ctx.send("An error occurred while disabling the database.")

    @cog.hybrid_command()
    @commands.guild_only()
    @app_commands.describe(url="The URL of the video to check")
    async def checkarchived(ctx: commands.Context, url: str):
        """Check if a video URL has been archived and get its Discord link if it exists."""
        try:
            if not cog.db:
                await ctx.send(
                    "The archive database is not enabled. Ask an admin to enable it with `/archivedb enable`"
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
                await ctx.send(embed=embed)
            else:
                embed = discord.Embed(
                    title="Video Not Found",
                    description="This video has not been archived yet.",
                    color=discord.Color.red(),
                )
                await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error checking archived video: {e}")
            await ctx.send("An error occurred while checking the archive.")

    @cog.hybrid_group(name="archiver", fallback="help")
    @commands.guild_only()
    async def archiver(ctx: commands.Context):
        """Manage video archiver settings."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @archiver.command(name="enable")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def enable_archiver(ctx: commands.Context):
        """Enable video archiving in this server."""
        try:
            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id, "enabled"
            )
            if current_setting:
                await ctx.send("Video archiving is already enabled.")
                return

            await cog.config_manager.update_setting(ctx.guild.id, "enabled", True)
            await ctx.send("Video archiving has been enabled.")

        except Exception as e:
            logger.error(f"Error enabling archiver: {e}")
            await ctx.send("An error occurred while enabling video archiving.")

    @archiver.command(name="disable")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def disable_archiver(ctx: commands.Context):
        """Disable video archiving in this server."""
        try:
            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id, "enabled"
            )
            if not current_setting:
                await ctx.send("Video archiving is already disabled.")
                return

            await cog.config_manager.update_setting(ctx.guild.id, "enabled", False)
            await ctx.send("Video archiving has been disabled.")

        except Exception as e:
            logger.error(f"Error disabling archiver: {e}")
            await ctx.send("An error occurred while disabling video archiving.")

    @archiver.command(name="setchannel")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where archived videos will be stored")
    async def set_archive_channel(ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel where archived videos will be stored."""
        try:
            await cog.config_manager.update_setting(
                ctx.guild.id, "archive_channel", channel.id
            )
            await ctx.send(f"Archive channel has been set to {channel.mention}.")
        except Exception as e:
            logger.error(f"Error setting archive channel: {e}")
            await ctx.send("An error occurred while setting the archive channel.")

    @archiver.command(name="setlog")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where log messages will be sent")
    async def set_log_channel(ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel where log messages will be sent."""
        try:
            await cog.config_manager.update_setting(
                ctx.guild.id, "log_channel", channel.id
            )
            await ctx.send(f"Log channel has been set to {channel.mention}.")
        except Exception as e:
            logger.error(f"Error setting log channel: {e}")
            await ctx.send("An error occurred while setting the log channel.")

    @archiver.command(name="addchannel")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to monitor for videos")
    async def add_enabled_channel(ctx: commands.Context, channel: discord.TextChannel):
        """Add a channel to monitor for videos."""
        try:
            enabled_channels = await cog.config_manager.get_setting(
                ctx.guild.id, "enabled_channels"
            )
            if channel.id in enabled_channels:
                await ctx.send(f"{channel.mention} is already being monitored.")
                return

            enabled_channels.append(channel.id)
            await cog.config_manager.update_setting(
                ctx.guild.id, "enabled_channels", enabled_channels
            )
            await ctx.send(f"Now monitoring {channel.mention} for videos.")
        except Exception as e:
            logger.error(f"Error adding enabled channel: {e}")
            await ctx.send("An error occurred while adding the channel.")

    @archiver.command(name="removechannel")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to stop monitoring")
    async def remove_enabled_channel(ctx: commands.Context, channel: discord.TextChannel):
        """Remove a channel from video monitoring."""
        try:
            enabled_channels = await cog.config_manager.get_setting(
                ctx.guild.id, "enabled_channels"
            )
            if channel.id not in enabled_channels:
                await ctx.send(f"{channel.mention} is not being monitored.")
                return

            enabled_channels.remove(channel.id)
            await cog.config_manager.update_setting(
                ctx.guild.id, "enabled_channels", enabled_channels
            )
            await ctx.send(f"Stopped monitoring {channel.mention} for videos.")
        except Exception as e:
            logger.error(f"Error removing enabled channel: {e}")
            await ctx.send("An error occurred while removing the channel.")

    # Error handling for commands
    @cog.cog_command_error
    async def cog_command_error(ctx: commands.Context, error: Exception) -> None:
        """Handle command errors"""
        error_msg = None
        try:
            if isinstance(error, commands.MissingPermissions):
                error_msg = "❌ You don't have permission to use this command."
            elif isinstance(error, commands.BotMissingPermissions):
                error_msg = "❌ I don't have the required permissions to do that."
            elif isinstance(error, commands.MissingRequiredArgument):
                error_msg = f"❌ Missing required argument: {error.param.name}"
            elif isinstance(error, commands.BadArgument):
                error_msg = f"❌ Invalid argument: {str(error)}"
            elif isinstance(error, ConfigError):
                error_msg = f"❌ Configuration error: {str(error)}"
            elif isinstance(error, ProcessingError):
                error_msg = f"❌ Processing error: {str(error)}"
            else:
                logger.error(
                    f"Command error in {ctx.command}: {traceback.format_exc()}"
                )
                error_msg = (
                    "❌ An unexpected error occurred. Check the logs for details."
                )

            if error_msg:
                await ctx.send(error_msg)

        except Exception as e:
            logger.error(f"Error handling command error: {str(e)}")
            try:
                await ctx.send(
                    "❌ An error occurred while handling another error. Please check the logs."
                )
            except Exception:
                pass  # Give up if we can't even send error messages
