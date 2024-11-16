"""Module for database-related commands"""

import discord
from redbot.core.commands import Context, hybrid_group, guild_only, admin_or_permissions
from discord import app_commands
import logging
from typing import Optional, Any, Dict, TypedDict, Tuple, Union
from enum import Enum, auto
from datetime import datetime

from ..response_handler import handle_response, ResponseType
from ...utils.exceptions import (
    CommandError,
    ErrorContext,
    ErrorSeverity,
    DatabaseError
)
from ...database.video_archive_db import VideoArchiveDB

logger = logging.getLogger("VideoArchiver")

class DatabaseOperation(Enum):
    """Database operation types"""
    ENABLE = auto()
    DISABLE = auto()
    QUERY = auto()
    MAINTENANCE = auto()

class DatabaseStatus(TypedDict):
    """Type definition for database status"""
    enabled: bool
    connected: bool
    initialized: bool
    error: Optional[str]
    last_operation: Optional[str]
    operation_time: Optional[str]

class ArchivedVideo(TypedDict):
    """Type definition for archived video data"""
    url: str
    discord_url: str
    message_id: int
    channel_id: int
    guild_id: int
    archived_at: str

async def check_database_status(cog: Any) -> DatabaseStatus:
    """
    Check database status.
    
    Args:
        cog: VideoArchiver cog instance
        
    Returns:
        Database status information
    """
    try:
        enabled = await cog.config_manager.get_setting(
            None, "use_database"
        ) if cog.config_manager else False

        return DatabaseStatus(
            enabled=enabled,
            connected=cog.db is not None and cog.db.is_connected(),
            initialized=cog.db is not None,
            error=None,
            last_operation=None,
            operation_time=datetime.utcnow().isoformat()
        )
    except Exception as e:
        return DatabaseStatus(
            enabled=False,
            connected=False,
            initialized=False,
            error=str(e),
            last_operation=None,
            operation_time=datetime.utcnow().isoformat()
        )

def setup_database_commands(cog: Any) -> Any:
    """
    Set up database commands for the cog.
    
    Args:
        cog: VideoArchiver cog instance
        
    Returns:
        Main database command group
    """

    @hybrid_group(name="archivedb", fallback="help")
    @guild_only()
    async def archivedb(ctx: Context) -> None:
        """Manage the video archive database."""
        if ctx.invoked_subcommand is None:
            try:
                # Get database status
                status = await check_database_status(cog)
                
                # Create status embed
                embed = discord.Embed(
                    title="Video Archive Database Status",
                    color=discord.Color.blue() if status["enabled"] else discord.Color.red()
                )
                embed.add_field(
                    name="Status",
                    value="Enabled" if status["enabled"] else "Disabled",
                    inline=False
                )
                embed.add_field(
                    name="Connection",
                    value="Connected" if status["connected"] else "Disconnected",
                    inline=True
                )
                embed.add_field(
                    name="Initialization",
                    value="Initialized" if status["initialized"] else "Not Initialized",
                    inline=True
                )
                if status["error"]:
                    embed.add_field(
                        name="Error",
                        value=status["error"],
                        inline=False
                    )
                
                await handle_response(
                    ctx,
                    "Use `/help archivedb` for a list of commands.",
                    embed=embed,
                    response_type=ResponseType.INFO
                )
            except Exception as e:
                error = f"Failed to get database status: {str(e)}"
                logger.error(error, exc_info=True)
                raise CommandError(
                    error,
                    context=ErrorContext(
                        "DatabaseCommands",
                        "show_status",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.MEDIUM
                    )
                )

    @archivedb.command(name="enable")
    @guild_only()
    @admin_or_permissions(administrator=True)
    async def enable_database(ctx: Context) -> None:
        """Enable the video archive database."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "DatabaseCommands",
                        "enable_database",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            # Check if database is already enabled
            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id, "use_database"
            )
            if current_setting:
                await handle_response(
                    ctx,
                    "The video archive database is already enabled.",
                    response_type=ResponseType.WARNING
                )
                return

            # Initialize database
            try:
                cog.db = VideoArchiveDB(cog.data_path)
                await cog.db.initialize()
            except Exception as e:
                raise DatabaseError(
                    f"Failed to initialize database: {str(e)}",
                    context=ErrorContext(
                        "DatabaseCommands",
                        "enable_database",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Update processor with database
            if cog.processor:
                cog.processor.db = cog.db
                if cog.processor.queue_handler:
                    cog.processor.queue_handler.db = cog.db

            # Update setting
            await cog.config_manager.update_setting(
                ctx.guild.id,
                "use_database",
                True
            )

            # Send success message
            await handle_response(
                ctx,
                "Video archive database has been enabled.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to enable database: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "DatabaseCommands",
                    "enable_database",
                    {"guild_id": ctx.guild.id},
                    ErrorSeverity.HIGH
                )
            )

    @archivedb.command(name="disable")
    @guild_only()
    @admin_or_permissions(administrator=True)
    async def disable_database(ctx: Context) -> None:
        """Disable the video archive database."""
        try:
            # Check if config manager is ready
            if not cog.config_manager:
                raise CommandError(
                    "Configuration system is not ready",
                    context=ErrorContext(
                        "DatabaseCommands",
                        "disable_database",
                        {"guild_id": ctx.guild.id},
                        ErrorSeverity.HIGH
                    )
                )

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id,
                "use_database"
            )
            if not current_setting:
                await handle_response(
                    ctx,
                    "The video archive database is already disabled.",
                    response_type=ResponseType.WARNING
                )
                return

            # Close database connection if active
            if cog.db:
                try:
                    await cog.db.close()
                except Exception as e:
                    logger.error(f"Error closing database connection: {e}")

            # Remove database references
            cog.db = None
            if cog.processor:
                cog.processor.db = None
                if cog.processor.queue_handler:
                    cog.processor.queue_handler.db = None

            await cog.config_manager.update_setting(
                ctx.guild.id,
                "use_database",
                False
            )
            await handle_response(
                ctx,
                "Video archive database has been disabled.",
                response_type=ResponseType.SUCCESS
            )

        except Exception as e:
            error = f"Failed to disable database: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "DatabaseCommands",
                    "disable_database",
                    {"guild_id": ctx.guild.id},
                    ErrorSeverity.HIGH
                )
            )

    @archivedb.command(name="check")
    @guild_only()
    @app_commands.describe(url="The URL of the video to check")
    async def checkarchived(ctx: Context, url: str) -> None:
        """Check if a video URL has been archived and get its Discord link if it exists."""
        try:
            # Check if database is enabled
            if not cog.db:
                await handle_response(
                    ctx,
                    "The archive database is not enabled. Ask an admin to enable it with `/archivedb enable`",
                    response_type=ResponseType.ERROR
                )
                return

            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            try:
                result = await cog.db.get_archived_video(url)
            except Exception as e:
                raise DatabaseError(
                    f"Failed to query database: {str(e)}",
                    context=ErrorContext(
                        "DatabaseCommands",
                        "checkarchived",
                        {"guild_id": ctx.guild.id, "url": url},
                        ErrorSeverity.MEDIUM
                    )
                )

            if result:
                discord_url, message_id, channel_id, guild_id = result
                embed = discord.Embed(
                    title="Video Found in Archive",
                    description=f"This video has been archived!\n\nOriginal URL: {url}",
                    color=discord.Color.green(),
                )
                embed.add_field(
                    name="Archived Link",
                    value=discord_url,
                    inline=False
                )
                embed.add_field(
                    name="Message ID",
                    value=str(message_id),
                    inline=True
                )
                embed.add_field(
                    name="Channel ID",
                    value=str(channel_id),
                    inline=True
                )
                embed.add_field(
                    name="Guild ID",
                    value=str(guild_id),
                    inline=True
                )
                await handle_response(
                    ctx,
                    embed=embed,
                    response_type=ResponseType.SUCCESS
                )
            else:
                embed = discord.Embed(
                    title="Video Not Found",
                    description="This video has not been archived yet.",
                    color=discord.Color.red(),
                )
                await handle_response(
                    ctx,
                    embed=embed,
                    response_type=ResponseType.WARNING
                )

        except Exception as e:
            error = f"Failed to check archived video: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "DatabaseCommands",
                    "checkarchived",
                    {"guild_id": ctx.guild.id, "url": url},
                    ErrorSeverity.MEDIUM
                )
            )

    @archivedb.command(name="status")
    @guild_only()
    @admin_or_permissions(administrator=True)
    async def database_status(ctx: Context) -> None:
        """Show detailed database status information."""
        try:
            # Defer the response immediately for slash commands
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.defer()

            status = await check_database_status(cog)
            
            # Get additional stats if database is enabled
            stats = {}
            if cog.db and status["connected"]:
                try:
                    stats = await cog.db.get_stats()
                except Exception as e:
                    logger.error(f"Error getting database stats: {e}")

            embed = discord.Embed(
                title="Database Status",
                color=discord.Color.green() if status["connected"] else discord.Color.red()
            )
            embed.add_field(
                name="Status",
                value="Enabled" if status["enabled"] else "Disabled",
                inline=False
            )
            embed.add_field(
                name="Connection",
                value="Connected" if status["connected"] else "Disconnected",
                inline=True
            )
            embed.add_field(
                name="Initialization",
                value="Initialized" if status["initialized"] else "Not Initialized",
                inline=True
            )

            if stats:
                embed.add_field(
                    name="Total Videos",
                    value=str(stats.get("total_videos", 0)),
                    inline=True
                )
                embed.add_field(
                    name="Total Size",
                    value=f"{stats.get('total_size', 0)} MB",
                    inline=True
                )
                embed.add_field(
                    name="Last Update",
                    value=stats.get("last_update", "Never"),
                    inline=True
                )

            if status["error"]:
                embed.add_field(
                    name="Error",
                    value=status["error"],
                    inline=False
                )

            await handle_response(
                ctx,
                embed=embed,
                response_type=ResponseType.INFO
            )

        except Exception as e:
            error = f"Failed to get database status: {str(e)}"
            logger.error(error, exc_info=True)
            raise CommandError(
                error,
                context=ErrorContext(
                    "DatabaseCommands",
                    "database_status",
                    {"guild_id": ctx.guild.id},
                    ErrorSeverity.MEDIUM
                )
            )

    # Store commands in cog for access
    cog.archivedb = archivedb
    cog.enable_database = enable_database
    cog.disable_database = disable_database
    cog.checkarchived = checkarchived
    cog.database_status = database_status

    return archivedb
