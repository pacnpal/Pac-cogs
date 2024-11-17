"""Module for core archiver commands"""

import logging
from enum import Enum, auto
from typing import Optional, Any, Dict, TypedDict, Callable, Awaitable

import discord # type: ignore
from discord import app_commands # type: ignore
from redbot.core import commands # type: ignore
from redbot.core.commands import Context, hybrid_group, guild_only, admin_or_permissions # type: ignore

from core.response_handler import handle_response, ResponseType
from utils.exceptions import CommandError, ErrorContext, ErrorSeverity

logger = logging.getLogger("VideoArchiver")


class CommandCategory(Enum):
    """Command categories"""

    MANAGEMENT = auto()
    STATUS = auto()
    UTILITY = auto()


class CommandResult(TypedDict):
    """Type definition for command result"""

    success: bool
    message: str
    details: Optional[Dict[str, Any]]
    error: Optional[str]


class CommandContext:
    """Context manager for command execution"""

    def __init__(self, ctx: Context, category: CommandCategory, operation: str) -> None:
        self.ctx = ctx
        self.category = category
        self.operation = operation
        self.start_time = None

    async def __aenter__(self) -> "CommandContext":
        """Set up command context"""
        self.start_time = self.ctx.message.created_at
        logger.debug(
            f"Starting command {self.operation} in category {self.category.name}"
        )
        if hasattr(self.ctx, "interaction") and self.ctx.interaction:
            await self.ctx.defer()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Handle command completion or error"""
        if exc_type is not None:
            error = f"Error in {self.operation}: {str(exc_val)}"
            logger.error(error, exc_info=True)
            await handle_response(
                self.ctx,
                f"An error occurred: {str(exc_val)}",
                response_type=ResponseType.ERROR,
            )
            return True
        return False


def setup_archiver_commands(cog: Any) -> Callable:
    """
    Set up archiver commands for the cog.

    Args:
        cog: VideoArchiver cog instance

    Returns:
        Main archiver command group
    """

    @hybrid_group(name="archiver", fallback="help")
    @guild_only()
    async def archiver(ctx: Context) -> None:
        """Manage video archiver settings."""
        if ctx.invoked_subcommand is None:
            await handle_response(
                ctx,
                "Use `/help archiver` for a list of commands.",
                response_type=ResponseType.INFO,
            )

    @archiver.command(name="enable")
    @guild_only()
    @admin_or_permissions(administrator=True)
    async def enable_archiver(ctx: Context) -> None:
        """Enable video archiving in this server."""
        async with CommandContext(ctx, CommandCategory.MANAGEMENT, "enable_archiver"):
            try:
                # Check if config manager is ready
                if not cog.config_manager:
                    raise CommandError(
                        "Configuration system is not ready",
                        context=ErrorContext(
                            "ArchiverCommands",
                            "enable_archiver",
                            {"guild_id": ctx.guild.id},
                            ErrorSeverity.HIGH,
                        ),
                    )

                # Check current setting
                current_setting = await cog.config_manager.get_setting(
                    ctx.guild.id, "enabled"
                )
                if current_setting:
                    await handle_response(
                        ctx,
                        "Video archiving is already enabled.",
                        response_type=ResponseType.WARNING,
                    )
                    return

                # Update setting
                await cog.config_manager.update_setting(ctx.guild.id, "enabled", True)
                await handle_response(
                    ctx,
                    "Video archiving has been enabled.",
                    response_type=ResponseType.SUCCESS,
                )

            except Exception as e:
                error = f"Failed to enable archiver: {str(e)}"
                logger.error(error, exc_info=True)
                raise CommandError(
                    error,
                    context=ErrorContext(
                        "ArchiverCommands",
                        "enable_archiver",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH,
                    ),
                )

    @archiver.command(name="disable")
    @guild_only()
    @admin_or_permissions(administrator=True)
    async def disable_archiver(ctx: Context) -> None:
        """Disable video archiving in this server."""
        async with CommandContext(ctx, CommandCategory.MANAGEMENT, "disable_archiver"):
            try:
                # Check if config manager is ready
                if not cog.config_manager:
                    raise CommandError(
                        "Configuration system is not ready",
                        context=ErrorContext(
                            "ArchiverCommands",
                            "disable_archiver",
                            {"guild_id": ctx.guild.id},
                            ErrorSeverity.HIGH,
                        ),
                    )

                # Check current setting
                current_setting = await cog.config_manager.get_setting(
                    ctx.guild.id, "enabled"
                )
                if not current_setting:
                    await handle_response(
                        ctx,
                        "Video archiving is already disabled.",
                        response_type=ResponseType.WARNING,
                    )
                    return

                # Update setting
                await cog.config_manager.update_setting(ctx.guild.id, "enabled", False)
                await handle_response(
                    ctx,
                    "Video archiving has been disabled.",
                    response_type=ResponseType.SUCCESS,
                )

            except Exception as e:
                error = f"Failed to disable archiver: {str(e)}"
                logger.error(error, exc_info=True)
                raise CommandError(
                    error,
                    context=ErrorContext(
                        "ArchiverCommands",
                        "disable_archiver",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH,
                    ),
                )

    @archiver.command(name="queue")
    @guild_only()
    async def show_queue(ctx: Context) -> None:
        """Show the current video processing queue."""
        async with CommandContext(ctx, CommandCategory.STATUS, "show_queue"):
            try:
                # Check if processor is ready
                if not cog.processor:
                    raise CommandError(
                        "Video processor is not ready",
                        context=ErrorContext(
                            "ArchiverCommands",
                            "show_queue",
                            {"guild_id": ctx.guild.id},
                            ErrorSeverity.MEDIUM,
                        ),
                    )

                await cog.processor.show_queue_details(ctx)

            except Exception as e:
                error = f"Failed to show queue: {str(e)}"
                logger.error(error, exc_info=True)
                raise CommandError(
                    error,
                    context=ErrorContext(
                        "ArchiverCommands",
                        "show_queue",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.MEDIUM,
                    ),
                )

    @archiver.command(name="status")
    @guild_only()
    @admin_or_permissions(administrator=True)
    async def show_status(ctx: Context) -> None:
        """Show the archiver status for this server."""
        async with CommandContext(ctx, CommandCategory.STATUS, "show_status"):
            try:
                # Get comprehensive status
                status = {
                    "enabled": await cog.config_manager.get_setting(
                        ctx.guild.id, "enabled"
                    ),
                    "queue": (
                        cog.queue_manager.get_queue_status(ctx.guild.id)
                        if cog.queue_manager
                        else None
                    ),
                    "processor": cog.processor.get_status() if cog.processor else None,
                    "components": cog.component_manager.get_component_status(),
                    "health": cog.status_tracker.get_status(),
                }

                # Create status embed
                embed = discord.Embed(
                    title="VideoArchiver Status",
                    color=(
                        discord.Color.blue()
                        if status["enabled"]
                        else discord.Color.red()
                    ),
                )
                embed.add_field(
                    name="Status",
                    value="Enabled" if status["enabled"] else "Disabled",
                    inline=False,
                )

                if status["queue"]:
                    embed.add_field(
                        name="Queue",
                        value=(
                            f"Pending: {status['queue']['pending']}\n"
                            f"Processing: {status['queue']['processing']}\n"
                            f"Completed: {status['queue']['completed']}"
                        ),
                        inline=True,
                    )

                if status["processor"]:
                    embed.add_field(
                        name="Processor",
                        value=(
                            f"Active: {status['processor']['active']}\n"
                            f"Health: {status['processor']['health']}"
                        ),
                        inline=True,
                    )

                embed.add_field(
                    name="Health",
                    value=(
                        f"State: {status['health']['state']}\n"
                        f"Errors: {status['health']['error_count']}"
                    ),
                    inline=True,
                )

                await ctx.send(embed=embed)

            except Exception as e:
                error = f"Failed to show status: {str(e)}"
                logger.error(error, exc_info=True)
                raise CommandError(
                    error,
                    context=ErrorContext(
                        "ArchiverCommands",
                        "show_status",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.MEDIUM,
                    ),
                )

    # Store commands in cog for access
    cog.archiver = archiver
    cog.enable_archiver = enable_archiver
    cog.disable_archiver = disable_archiver
    cog.show_queue = show_queue
    cog.show_status = show_status

    return archiver
