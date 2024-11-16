"""Module for settings-related commands"""

import discord
from redbot.core.commands import Context, hybrid_group, guild_only, admin_or_permissions
from discord import app_commands
import logging
from ..response_handler import handle_response

logger = logging.getLogger("VideoArchiver")

def setup_settings_commands(cog):
    """Set up settings commands for the cog"""

    @cog.hybrid_group(name="settings", fallback="show")
    @guild_only()
    async def settings(ctx: Context):
        """Show current archiver settings."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            embed = await cog.config_manager.format_settings_embed(ctx.guild)
            await handle_response(ctx, embed=embed)
        except Exception as e:
            logger.error(f"Error showing settings: {e}")
            await handle_response(
                ctx, "An error occurred while showing settings."
            )

    @settings.command(name="setchannel")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where archived videos will be stored")
    async def set_archive_channel(ctx: Context, channel: discord.TextChannel):
        """Set the channel where archived videos will be stored."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            await cog.config_manager.update_setting(
                ctx.guild.id, "archive_channel", channel.id
            )
            await handle_response(
                ctx, f"Archive channel has been set to {channel.mention}."
            )
        except Exception as e:
            logger.error(f"Error setting archive channel: {e}")
            await handle_response(
                ctx, "An error occurred while setting the archive channel."
            )

    @settings.command(name="setlog")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where log messages will be sent")
    async def set_log_channel(ctx: Context, channel: discord.TextChannel):
        """Set the channel where log messages will be sent."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            await cog.config_manager.update_setting(
                ctx.guild.id, "log_channel", channel.id
            )
            await handle_response(
                ctx, f"Log channel has been set to {channel.mention}."
            )
        except Exception as e:
            logger.error(f"Error setting log channel: {e}")
            await handle_response(
                ctx, "An error occurred while setting the log channel."
            )

    @settings.command(name="addchannel")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to monitor for videos")
    async def add_enabled_channel(ctx: Context, channel: discord.TextChannel):
        """Add a channel to monitor for videos."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            enabled_channels = await cog.config_manager.get_setting(
                ctx.guild.id, "enabled_channels"
            )
            if channel.id in enabled_channels:
                await handle_response(
                    ctx, f"{channel.mention} is already being monitored."
                )
                return

            enabled_channels.append(channel.id)
            await cog.config_manager.update_setting(
                ctx.guild.id, "enabled_channels", enabled_channels
            )
            await handle_response(
                ctx, f"Now monitoring {channel.mention} for videos."
            )
        except Exception as e:
            logger.error(f"Error adding enabled channel: {e}")
            await handle_response(
                ctx, "An error occurred while adding the channel."
            )

    @settings.command(name="removechannel")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to stop monitoring")
    async def remove_enabled_channel(ctx: Context, channel: discord.TextChannel):
        """Remove a channel from video monitoring."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            enabled_channels = await cog.config_manager.get_setting(
                ctx.guild.id, "enabled_channels"
            )
            if channel.id not in enabled_channels:
                await handle_response(
                    ctx, f"{channel.mention} is not being monitored."
                )
                return

            enabled_channels.remove(channel.id)
            await cog.config_manager.update_setting(
                ctx.guild.id, "enabled_channels", enabled_channels
            )
            await handle_response(
                ctx, f"Stopped monitoring {channel.mention} for videos."
            )
        except Exception as e:
            logger.error(f"Error removing enabled channel: {e}")
            await handle_response(
                ctx, "An error occurred while removing the channel."
            )

    @settings.command(name="setformat")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(format="The video format to use (mp4, webm, or mkv)")
    async def set_video_format(ctx: Context, format: str):
        """Set the video format for archived videos."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            format = format.lower()
            if format not in ["mp4", "webm", "mkv"]:
                await handle_response(
                    ctx, "Invalid format. Please use mp4, webm, or mkv."
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id, "video_format", format
            )
            await handle_response(ctx, f"Video format has been set to {format}.")
        except Exception as e:
            logger.error(f"Error setting video format: {e}")
            await handle_response(
                ctx, "An error occurred while setting the video format."
            )

    @settings.command(name="setquality")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(quality="The video quality (144-4320)")
    async def set_video_quality(ctx: Context, quality: int):
        """Set the video quality for archived videos."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            if not 144 <= quality <= 4320:
                await handle_response(
                    ctx, "Quality must be between 144 and 4320."
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id, "video_quality", quality
            )
            await handle_response(
                ctx, f"Video quality has been set to {quality}p."
            )
        except Exception as e:
            logger.error(f"Error setting video quality: {e}")
            await handle_response(
                ctx, "An error occurred while setting the video quality."
            )

    @settings.command(name="setmaxsize")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(size="The maximum file size in MB (1-100)")
    async def set_max_file_size(ctx: Context, size: int):
        """Set the maximum file size for archived videos."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            if not 1 <= size <= 100:
                await handle_response(ctx, "Size must be between 1 and 100 MB.")
                return

            await cog.config_manager.update_setting(
                ctx.guild.id, "max_file_size", size
            )
            await handle_response(
                ctx, f"Maximum file size has been set to {size}MB."
            )
        except Exception as e:
            logger.error(f"Error setting max file size: {e}")
            await handle_response(
                ctx, "An error occurred while setting the maximum file size."
            )

    @settings.command(name="setmessageduration")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(hours="How long to keep messages in hours (0-168)")
    async def set_message_duration(ctx: Context, hours: int):
        """Set how long to keep archived messages."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            if not 0 <= hours <= 168:
                await handle_response(
                    ctx, "Duration must be between 0 and 168 hours (1 week)."
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id, "message_duration", hours
            )
            await handle_response(
                ctx, f"Message duration has been set to {hours} hours."
            )
        except Exception as e:
            logger.error(f"Error setting message duration: {e}")
            await handle_response(
                ctx, "An error occurred while setting the message duration."
            )

    @settings.command(name="settemplate")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(
        template="The message template to use. Available placeholders: {author}, {channel}, {original_message}"
    )
    async def set_message_template(ctx: Context, template: str):
        """Set the template for archived messages."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            if not any(
                ph in template for ph in ["{author}", "{channel}", "{original_message}"]
            ):
                await handle_response(
                    ctx,
                    "Template must include at least one placeholder: {author}, {channel}, or {original_message}",
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id, "message_template", template
            )
            await handle_response(
                ctx, f"Message template has been set to: {template}"
            )
        except Exception as e:
            logger.error(f"Error setting message template: {e}")
            await handle_response(
                ctx, "An error occurred while setting the message template."
            )

    @settings.command(name="setconcurrent")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(count="Number of concurrent downloads (1-5)")
    async def set_concurrent_downloads(ctx: Context, count: int):
        """Set the number of concurrent downloads allowed."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            if not 1 <= count <= 5:
                await handle_response(
                    ctx, "Concurrent downloads must be between 1 and 5."
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id, "concurrent_downloads", count
            )
            await handle_response(
                ctx, f"Concurrent downloads has been set to {count}."
            )
        except Exception as e:
            logger.error(f"Error setting concurrent downloads: {e}")
            await handle_response(
                ctx, "An error occurred while setting concurrent downloads."
            )

    # Store commands in cog for access
    cog.settings = settings
    cog.set_archive_channel = set_archive_channel
    cog.set_log_channel = set_log_channel
    cog.add_enabled_channel = add_enabled_channel
    cog.remove_enabled_channel = remove_enabled_channel
    cog.set_video_format = set_video_format
    cog.set_video_quality = set_video_quality
    cog.set_max_file_size = set_max_file_size
    cog.set_message_duration = set_message_duration
    cog.set_message_template = set_message_template
    cog.set_concurrent_downloads = set_concurrent_downloads

    return settings
