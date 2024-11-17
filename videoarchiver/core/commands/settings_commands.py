"""Module for settings-related commands"""

import logging
from enum import Enum, auto
from typing import Optional, Any, Dict, TypedDict

import discord
from discord import app_commands
from redbot.core import commands
from redbot.core.commands import Context, hybrid_group, guild_only, admin_or_permissions

from .core.settings import VideoFormat, VideoQuality
from .core.response_handler import handle_response, ResponseType
from .utils.exceptions import (
    CommandError,
    ErrorContext,
    ErrorSeverity
)

logger = logging.getLogger("VideoArchiver")

class SettingCategory(Enum):
    """Setting categories"""
    CHANNELS = auto()
    VIDEO = auto()
    MESSAGES = auto()
    PERFORMANCE = auto()

class SettingValidation(TypedDict):
    """Type definition for setting validation"""
    valid: bool
    error: Optional[str]
    details: Dict[str, Any]

class SettingUpdate(TypedDict):
    """Type definition for setting update"""
    setting: str
    old_value: Any
    new_value: Any
    category: SettingCategory

async def validate_setting(
    category: SettingCategory,
    setting: str,
    value: Any
) -> SettingValidation:
    """
    Validate a setting value.
    
    Args:
        category: Setting category
        setting: Setting name
        value: Value to validate
        
    Returns:
        Validation result
    """
    validation = SettingValidation(
        valid=True,
        error=None,
        details={"category": category.name, "setting": setting, "value": value}
    )

    try:
        if category == SettingCategory.VIDEO:
            if setting == "format":
                if value not in [f.value for f in VideoFormat]:
                    validation.update({
                        "valid": False,
                        "error": f"Invalid format. Must be one of: {', '.join(f.value for f in VideoFormat)}"
                    })
            elif setting == "quality":
                if not 144 <= value <= 4320:
                    validation.update({
                        "valid": False,
                        "error": "Quality must be between 144 and 4320"
                    })
            elif setting == "max_file_size":
                if not 1 <= value <= 100:
                    validation.update({
                        "valid": False,
                        "error": "Size must be between 1 and 100 MB"
                    })

        elif category == SettingCategory.MESSAGES:
            if setting == "duration":
                if not 0 <= value <= 168:
                    validation.update({
                        "valid": False,
                        "error": "Duration must be between 0 and 168 hours (1 week)"
                    })
            elif setting == "template":
                placeholders = ["{author}", "{channel}", "{original_message}"]
                if not any(ph in value for ph in placeholders):
                    validation.update({
                        "valid": False,
                        "error": f"Template must include at least one placeholder: {', '.join(placeholders)}"
                    })

        elif category == SettingCategory.PERFORMANCE:
            if setting == "concurrent_downloads":
                if not 1 <= value <= 5:
                    validation.update({
                        "valid": False,
                        "error": "Concurrent downloads must be between 1 and 5"
                    })

    except Exception as e:
        validation.update({
            "valid": False,
            "error": f"Validation error: {str(e)}"
        })

    return validation

def setup_settings_commands(cog: Any) -> Any:
    """
    Set up settings commands for the cog.
    
    Args:
        cog: VideoArchiver cog instance
        
    Returns:
        Main settings command group
    """

    @hybrid_group(name="settings", fallback="show")
    @guild_only()
    async def settings(ctx: Context) -> None:
        """Show current archiver settings."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "show_settings",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            embed = await cog.config_manager.format_settings_embed(ctx.guild)
            await handle_response(
                ctx,
                embed=embed,
                response_type=ResponseType.INFO
            )

        except Exception as e:
            error = f"Failed to show settings: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "show_settings",
                    {"guild_id": ctx.guild.id},
                    ErrorSeverity.MEDIUM
                )
            )

    @settings.command(name="setchannel")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where archived videos will be stored")
    async def set_archive_channel(ctx: Context, channel: discord.TextChannel) -> None:
        """Set the channel where archived videos will be stored."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_archive_channel",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Check channel permissions
            bot_member = ctx.guild.me
            required_perms = discord.Permissions(
                send_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True
            )
            channel_perms = channel.permissions_for(bot_member)
            if not all(getattr(channel_perms, perm) for perm in required_perms):
                raise CommandError(
                    "Missing required permissions in target channel",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_archive_channel",
                        {
                            "guild_id": ctx.guild.id,
                            "channel_id": channel.id,
                            "missing_perms": [
                                perm for perm in required_perms
                                if not getattr(channel_perms, perm)
                            ]
                        },
                        ErrorSeverity.MEDIUM
                    )
                )

            await cog.config_manager.update_setting(
                ctx.guild.id,
                "archive_channel",
                channel.id
            )
            await handle_response(
                ctx,
                f"Archive channel has been set to {channel.mention}.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to set archive channel: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "set_archive_channel",
                    {"guild_id": ctx.guild.id, "channel_id": channel.id},
                    ErrorSeverity.HIGH
                )
            )

    @settings.command(name="setlog")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where log messages will be sent")
    async def set_log_channel(ctx: Context, channel: discord.TextChannel) -> None:
        """Set the channel where log messages will be sent."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_log_channel",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Check channel permissions
            bot_member = ctx.guild.me
            required_perms = discord.Permissions(
                send_messages=True,
                embed_links=True,
                read_message_history=True
            )
            channel_perms = channel.permissions_for(bot_member)
            if not all(getattr(channel_perms, perm) for perm in required_perms):
                raise CommandError(
                    "Missing required permissions in target channel",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_log_channel",
                        {
                            "guild_id": ctx.guild.id,
                            "channel_id": channel.id,
                            "missing_perms": [
                                perm for perm in required_perms
                                if not getattr(channel_perms, perm)
                            ]
                        },
                        ErrorSeverity.MEDIUM
                    )
                )

            await cog.config_manager.update_setting(
                ctx.guild.id,
                "log_channel",
                channel.id
            )
            await handle_response(
                ctx,
                f"Log channel has been set to {channel.mention}.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to set log channel: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "set_log_channel",
                    {"guild_id": ctx.guild.id, "channel_id": channel.id},
                    ErrorSeverity.HIGH
                )
            )

    @settings.command(name="addchannel")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to monitor for videos")
    async def add_enabled_channel(ctx: Context, channel: discord.TextChannel) -> None:
        """Add a channel to monitor for videos."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "add_enabled_channel",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Check channel permissions
            bot_member = ctx.guild.me
            required_perms = discord.Permissions(
                read_messages=True,
                read_message_history=True
            )
            channel_perms = channel.permissions_for(bot_member)
            if not all(getattr(channel_perms, perm) for perm in required_perms):
                raise CommandError(
                    "Missing required permissions in target channel",
                    context=ErrorContext(
                        "SettingsCommands",
                        "add_enabled_channel",
                        {
                            "guild_id": ctx.guild.id,
                            "channel_id": channel.id,
                            "missing_perms": [
                                perm for perm in required_perms
                                if not getattr(channel_perms, perm)
                            ]
                        },
                        ErrorSeverity.MEDIUM
                    )
                )

            enabled_channels = await cog.config_manager.get_setting(
                ctx.guild.id,
                "enabled_channels"
            )
            if channel.id in enabled_channels:
                await handle_response(
                    ctx,
                    f"{channel.mention} is already being monitored.",
                    response_type=ResponseType.WARNING
                )
                return

            enabled_channels.append(channel.id)
            await cog.config_manager.update_setting(
                ctx.guild.id,
                "enabled_channels",
                enabled_channels
            )
            await handle_response(
                ctx,
                f"Now monitoring {channel.mention} for videos.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to add enabled channel: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "add_enabled_channel",
                    {"guild_id": ctx.guild.id, "channel_id": channel.id},
                    ErrorSeverity.HIGH
                )
            )

    @settings.command(name="removechannel")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to stop monitoring")
    async def remove_enabled_channel(ctx: Context, channel: discord.TextChannel) -> None:
        """Remove a channel from video monitoring."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "remove_enabled_channel",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            enabled_channels = await cog.config_manager.get_setting(
                ctx.guild.id,
                "enabled_channels"
            )
            if channel.id not in enabled_channels:
                await handle_response(
                    ctx,
                    f"{channel.mention} is not being monitored.",
                    response_type=ResponseType.WARNING
                )
                return

            enabled_channels.remove(channel.id)
            await cog.config_manager.update_setting(
                ctx.guild.id,
                "enabled_channels",
                enabled_channels
            )
            await handle_response(
                ctx,
                f"Stopped monitoring {channel.mention} for videos.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to remove enabled channel: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "remove_enabled_channel",
                    {"guild_id": ctx.guild.id, "channel_id": channel.id},
                    ErrorSeverity.HIGH
                )
            )

    @settings.command(name="setformat")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(format="The video format to use (mp4, webm, or mkv)")
    async def set_video_format(ctx: Context, format: str) -> None:
        """Set the video format for archived videos."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_video_format",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Validate format
            format = format.lower()
            validation = await validate_setting(
                SettingCategory.VIDEO,
                "format",
                format
            )
            if not validation["valid"]:
                await handle_response(
                    ctx,
                    validation["error"],
                    response_type=ResponseType.ERROR
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id,
                "video_format",
                format
            )
            await handle_response(
                ctx,
                f"Video format has been set to {format}.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to set video format: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "set_video_format",
                    {"guild_id": ctx.guild.id, "format": format},
                    ErrorSeverity.HIGH
                )
            )

    @settings.command(name="setquality")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(quality="The video quality (144-4320)")
    async def set_video_quality(ctx: Context, quality: int) -> None:
        """Set the video quality for archived videos."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_video_quality",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Validate quality
            validation = await validate_setting(
                SettingCategory.VIDEO,
                "quality",
                quality
            )
            if not validation["valid"]:
                await handle_response(
                    ctx,
                    validation["error"],
                    response_type=ResponseType.ERROR
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id,
                "video_quality",
                quality
            )
            await handle_response(
                ctx,
                f"Video quality has been set to {quality}p.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to set video quality: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "set_video_quality",
                    {"guild_id": ctx.guild.id, "quality": quality},
                    ErrorSeverity.HIGH
                )
            )

    @settings.command(name="setmaxsize")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(size="The maximum file size in MB (1-100)")
    async def set_max_file_size(ctx: Context, size: int) -> None:
        """Set the maximum file size for archived videos."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_max_file_size",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Validate size
            validation = await validate_setting(
                SettingCategory.VIDEO,
                "max_file_size",
                size
            )
            if not validation["valid"]:
                await handle_response(
                    ctx,
                    validation["error"],
                    response_type=ResponseType.ERROR
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id,
                "max_file_size",
                size
            )
            await handle_response(
                ctx,
                f"Maximum file size has been set to {size}MB.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to set max file size: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "set_max_file_size",
                    {"guild_id": ctx.guild.id, "size": size},
                    ErrorSeverity.HIGH
                )
            )

    @settings.command(name="setmessageduration")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(hours="How long to keep messages in hours (0-168)")
    async def set_message_duration(ctx: Context, hours: int) -> None:
        """Set how long to keep archived messages."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_message_duration",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Validate duration
            validation = await validate_setting(
                SettingCategory.MESSAGES,
                "duration",
                hours
            )
            if not validation["valid"]:
                await handle_response(
                    ctx,
                    validation["error"],
                    response_type=ResponseType.ERROR
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id,
                "message_duration",
                hours
            )
            await handle_response(
                ctx,
                f"Message duration has been set to {hours} hours.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to set message duration: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "set_message_duration",
                    {"guild_id": ctx.guild.id, "hours": hours},
                    ErrorSeverity.HIGH
                )
            )

    @settings.command(name="settemplate")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(
        template="The message template to use. Available placeholders: {author}, {channel}, {original_message}"
    )
    async def set_message_template(ctx: Context, template: str) -> None:
        """Set the template for archived messages."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_message_template",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Validate template
            validation = await validate_setting(
                SettingCategory.MESSAGES,
                "template",
                template
            )
            if not validation["valid"]:
                await handle_response(
                    ctx,
                    validation["error"],
                    response_type=ResponseType.ERROR
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id,
                "message_template",
                template
            )
            await handle_response(
                ctx,
                f"Message template has been set to: {template}",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to set message template: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "set_message_template",
                    {"guild_id": ctx.guild.id},
                    ErrorSeverity.HIGH
                )
            )

    @settings.command(name="setconcurrent")
    @guild_only()
    @admin_or_permissions(administrator=True)
    @app_commands.describe(count="Number of concurrent downloads (1-5)")
    async def set_concurrent_downloads(ctx: Context, count: int) -> None:
        """Set the number of concurrent downloads allowed."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "SettingsCommands",
                        "set_concurrent_downloads",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Validate count
            validation = await validate_setting(
                SettingCategory.PERFORMANCE,
                "concurrent_downloads",
                count
            )
            if not validation["valid"]:
                await handle_response(
                    ctx,
                    validation["error"],
                    response_type=ResponseType.ERROR
                )
                return

            await cog.config_manager.update_setting(
                ctx.guild.id,
                "concurrent_downloads",
                count
            )
            await handle_response(
                ctx,
                f"Concurrent downloads has been set to {count}.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to set concurrent downloads: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "SettingsCommands",
                    "set_concurrent_downloads",
                    {"guild_id": ctx.guild.id, "count": count},
                    ErrorSeverity.HIGH
                )
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
