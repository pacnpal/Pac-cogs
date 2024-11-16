"""Base module containing core VideoArchiver class"""

from __future__ import annotations

import discord
import traceback
from redbot.core import Config, data_manager
from redbot.core.bot import Red
from redbot.core.commands import (
    GroupCog,
    Context,
    hybrid_command,
    hybrid_group,
    guild_only,
    commands,
    MissingPermissions,
    BotMissingPermissions,
    MissingRequiredArgument,
    BadArgument,
)
from redbot.core import checks
from discord import app_commands
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

from ..config_manager import ConfigManager
from ..update_checker import UpdateChecker
from ..processor import VideoProcessor
from ..utils.video_downloader import VideoDownloader
from ..utils.message_manager import MessageManager
from ..utils.file_ops import cleanup_downloads
from ..queue import EnhancedVideoQueueManager
from ..ffmpeg.ffmpeg_manager import FFmpegManager
from ..database.video_archive_db import VideoArchiveDB
from ..utils.exceptions import (
    VideoArchiverError as ProcessingError,
    ConfigurationError as ConfigError,
)

from .guild import initialize_guild_components
from .cleanup import cleanup_resources, force_cleanup_resources
from .events import setup_events

logger = logging.getLogger("VideoArchiver")

# Constants for timeouts - more reasonable timeouts
UNLOAD_TIMEOUT = 30  # seconds
CLEANUP_TIMEOUT = 15  # seconds
INIT_TIMEOUT = 60  # seconds
COMPONENT_INIT_TIMEOUT = 30  # seconds


class VideoArchiver(GroupCog):
    """Archive videos from Discord channels"""

    default_guild_settings = {
        "enabled": False,  # Changed to match config_manager.py
        "archive_channel": None,
        "log_channel": None,
        "enabled_channels": [],  # Empty list means all channels
        "allowed_roles": [],  # Empty list means all roles
        "video_format": "mp4",
        "video_quality": "high",
        "max_file_size": 8,  # MB
        "message_duration": 30,  # seconds
        "message_template": "{author} archived a video from {channel}",
        "concurrent_downloads": 2,
        "enabled_sites": None,  # None means all sites
        "use_database": False,  # Database tracking is off by default
    }

    def __init__(self, bot: Red) -> None:
        """Initialize the cog with minimal setup"""
        super().__init__()
        self.bot = bot
        self.ready = asyncio.Event()
        self._init_task = None
        self._cleanup_task = None
        self._queue_task = None
        self._unloading = False
        self.db = None
        self.queue_manager = None
        self.processor = None
        self.components = {}
        self.config_manager = None
        self.update_checker = None
        self.ffmpeg_mgr = None
        self.data_path = None
        self.download_path = None

        # Set up events - non-blocking
        setup_events(self)

    async def _handle_response(self, ctx: Context, content: str = None, embed: discord.Embed = None) -> None:
        """Helper method to handle responses for both regular commands and interactions"""
        try:
            if hasattr(ctx, 'interaction') and ctx.interaction:
                try:
                    # Check if this is a deferred interaction
                    if ctx.interaction.response.is_done():
                        # Use followup for deferred responses
                        if embed:
                            await ctx.followup.send(content=content, embed=embed, wait=True)
                        else:
                            await ctx.followup.send(content=content, wait=True)
                    else:
                        # Use regular response for non-deferred interactions
                        if embed:
                            await ctx.interaction.response.send_message(content=content, embed=embed)
                        else:
                            await ctx.interaction.response.send_message(content=content)
                except discord.errors.InteractionResponded:
                    # If we get here, the interaction was already responded to
                    # Use followup as a fallback
                    if embed:
                        await ctx.followup.send(content=content, embed=embed, wait=True)
                    else:
                        await ctx.followup.send(content=content, wait=True)
            else:
                # Regular command response
                if embed:
                    await ctx.send(content=content, embed=embed)
                else:
                    await ctx.send(content=content)
        except Exception as e:
            logger.error(f"Error sending response: {e}")
            # If all else fails, try to send a regular message
            try:
                if embed:
                    await ctx.send(content=content, embed=embed)
                else:
                    await ctx.send(content=content)
            except Exception as e2:
                logger.error(f"Failed to send fallback message: {e2}")

    @hybrid_group(name="archivedb", fallback="help")
    @guild_only()
    async def archivedb(self, ctx: Context):
        """Manage the video archive database."""
        if ctx.invoked_subcommand is None:
            await self._handle_response(ctx, "Use `/help archivedb` for a list of commands.")

    @archivedb.command(name="enable")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def enable_database(self, ctx: Context):
        """Enable the video archive database."""
        try:
            # Check if database is already enabled
            current_setting = await self.config_manager.get_setting(
                ctx.guild.id, "use_database"
            )
            if current_setting:
                await self._handle_response(ctx, "The video archive database is already enabled.")
                return

            # Initialize database
            self.db = VideoArchiveDB(self.data_path)
            
            # Update processor with database
            if self.processor:
                self.processor.db = self.db
                if self.processor.queue_handler:
                    self.processor.queue_handler.db = self.db

            # Update setting
            await self.config_manager.update_setting(ctx.guild.id, "use_database", True)
            
            # Send success message
            await self._handle_response(ctx, "Video archive database has been enabled.")

        except Exception as e:
            logger.error(f"Error enabling database: {e}")
            await self._handle_response(ctx, "An error occurred while enabling the database. Please check the logs for details.")

    @archivedb.command(name="disable")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def disable_database(self, ctx: Context):
        """Disable the video archive database."""
        try:
            current_setting = await self.config_manager.get_setting(
                ctx.guild.id, "use_database"
            )
            if not current_setting:
                await self._handle_response(ctx, "The video archive database is already disabled.")
                return

            # Remove database references
            self.db = None
            self.processor.db = None
            self.processor.queue_handler.db = None

            await self.config_manager.update_setting(
                ctx.guild.id, "use_database", False
            )
            await self._handle_response(ctx, "Video archive database has been disabled.")

        except Exception as e:
            logger.error(f"Error disabling database: {e}")
            await self._handle_response(ctx, "An error occurred while disabling the database.")

    @hybrid_command()
    @guild_only()
    @app_commands.describe(url="The URL of the video to check")
    async def checkarchived(self, ctx: Context, url: str):
        """Check if a video URL has been archived and get its Discord link if it exists."""
        try:
            if not self.db:
                await self._handle_response(
                    ctx, 
                    "The archive database is not enabled. Ask an admin to enable it with `/archivedb enable`"
                )
                return

            result = self.db.get_archived_video(url)
            if result:
                discord_url, message_id, channel_id, guild_id = result
                embed = discord.Embed(
                    title="Video Found in Archive",
                    description=f"This video has been archived!\n\nOriginal URL: {url}",
                    color=discord.Color.green(),
                )
                embed.add_field(name="Archived Link", value=discord_url)
                await self._handle_response(ctx, embed=embed)
            else:
                embed = discord.Embed(
                    title="Video Not Found",
                    description="This video has not been archived yet.",
                    color=discord.Color.red(),
                )
                await self._handle_response(ctx, embed=embed)
        except Exception as e:
            logger.error(f"Error checking archived video: {e}")
            await self._handle_response(ctx, "An error occurred while checking the archive.")

    @hybrid_group(name="archiver", fallback="help")
    @guild_only()
    async def archiver(self, ctx: Context):
        """Manage video archiver settings."""
        if ctx.invoked_subcommand is None:
            await self._handle_response(ctx, "Use `/help archiver` for a list of commands.")

    @archiver.command(name="enable")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def enable_archiver(self, ctx: Context):
        """Enable video archiving in this server."""
        try:
            current_setting = await self.config_manager.get_setting(
                ctx.guild.id, "enabled"
            )
            if current_setting:
                await self._handle_response(ctx, "Video archiving is already enabled.")
                return

            await self.config_manager.update_setting(ctx.guild.id, "enabled", True)
            await self._handle_response(ctx, "Video archiving has been enabled.")

        except Exception as e:
            logger.error(f"Error enabling archiver: {e}")
            await self._handle_response(ctx, "An error occurred while enabling video archiving.")

    @archiver.command(name="disable")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def disable_archiver(self, ctx: Context):
        """Disable video archiving in this server."""
        try:
            current_setting = await self.config_manager.get_setting(
                ctx.guild.id, "enabled"
            )
            if not current_setting:
                await self._handle_response(ctx, "Video archiving is already disabled.")
                return

            await self.config_manager.update_setting(ctx.guild.id, "enabled", False)
            await self._handle_response(ctx, "Video archiving has been disabled.")

        except Exception as e:
            logger.error(f"Error disabling archiver: {e}")
            await self._handle_response(ctx, "An error occurred while disabling video archiving.")

    @archiver.command(name="setchannel")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where archived videos will be stored")
    async def set_archive_channel(self, ctx: Context, channel: discord.TextChannel):
        """Set the channel where archived videos will be stored."""
        try:
            await self.config_manager.update_setting(
                ctx.guild.id, "archive_channel", channel.id
            )
            await self._handle_response(ctx, f"Archive channel has been set to {channel.mention}.")
        except Exception as e:
            logger.error(f"Error setting archive channel: {e}")
            await self._handle_response(ctx, "An error occurred while setting the archive channel.")

    @archiver.command(name="setlog")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where log messages will be sent")
    async def set_log_channel(self, ctx: Context, channel: discord.TextChannel):
        """Set the channel where log messages will be sent."""
        try:
            await self.config_manager.update_setting(
                ctx.guild.id, "log_channel", channel.id
            )
            await self._handle_response(ctx, f"Log channel has been set to {channel.mention}.")
        except Exception as e:
            logger.error(f"Error setting log channel: {e}")
            await self._handle_response(ctx, "An error occurred while setting the log channel.")

    @archiver.command(name="addchannel")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to monitor for videos")
    async def add_enabled_channel(self, ctx: Context, channel: discord.TextChannel):
        """Add a channel to monitor for videos."""
        try:
            enabled_channels = await self.config_manager.get_setting(
                ctx.guild.id, "enabled_channels"
            )
            if channel.id in enabled_channels:
                await self._handle_response(ctx, f"{channel.mention} is already being monitored.")
                return

            enabled_channels.append(channel.id)
            await self.config_manager.update_setting(
                ctx.guild.id, "enabled_channels", enabled_channels
            )
            await self._handle_response(ctx, f"Now monitoring {channel.mention} for videos.")
        except Exception as e:
            logger.error(f"Error adding enabled channel: {e}")
            await self._handle_response(ctx, "An error occurred while adding the channel.")

    @archiver.command(name="removechannel")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to stop monitoring")
    async def remove_enabled_channel(self, ctx: Context, channel: discord.TextChannel):
        """Remove a channel from video monitoring."""
        try:
            enabled_channels = await self.config_manager.get_setting(
                ctx.guild.id, "enabled_channels"
            )
            if channel.id not in enabled_channels:
                await self._handle_response(ctx, f"{channel.mention} is not being monitored.")
                return

            enabled_channels.remove(channel.id)
            await self.config_manager.update_setting(
                ctx.guild.id, "enabled_channels", enabled_channels
            )
            await self._handle_response(ctx, f"Stopped monitoring {channel.mention} for videos.")
        except Exception as e:
            logger.error(f"Error removing enabled channel: {e}")
            await self._handle_response(ctx, "An error occurred while removing the channel.")

    @archiver.command(name="setformat")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(format="The video format to use (mp4, webm, or mkv)")
    async def set_video_format(self, ctx: Context, format: str):
        """Set the video format for archived videos."""
        try:
            format = format.lower()
            if format not in ["mp4", "webm", "mkv"]:
                await self._handle_response(ctx, "Invalid format. Please use mp4, webm, or mkv.")
                return

            await self.config_manager.update_setting(ctx.guild.id, "video_format", format)
            await self._handle_response(ctx, f"Video format has been set to {format}.")
        except Exception as e:
            logger.error(f"Error setting video format: {e}")
            await self._handle_response(ctx, "An error occurred while setting the video format.")

    @archiver.command(name="setquality")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(quality="The video quality (144-4320)")
    async def set_video_quality(self, ctx: Context, quality: int):
        """Set the video quality for archived videos."""
        try:
            if not 144 <= quality <= 4320:
                await self._handle_response(ctx, "Quality must be between 144 and 4320.")
                return

            await self.config_manager.update_setting(ctx.guild.id, "video_quality", quality)
            await self._handle_response(ctx, f"Video quality has been set to {quality}p.")
        except Exception as e:
            logger.error(f"Error setting video quality: {e}")
            await self._handle_response(ctx, "An error occurred while setting the video quality.")

    @archiver.command(name="setmaxsize")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(size="The maximum file size in MB (1-100)")
    async def set_max_file_size(self, ctx: Context, size: int):
        """Set the maximum file size for archived videos."""
        try:
            if not 1 <= size <= 100:
                await self._handle_response(ctx, "Size must be between 1 and 100 MB.")
                return

            await self.config_manager.update_setting(ctx.guild.id, "max_file_size", size)
            await self._handle_response(ctx, f"Maximum file size has been set to {size}MB.")
        except Exception as e:
            logger.error(f"Error setting max file size: {e}")
            await self._handle_response(ctx, "An error occurred while setting the maximum file size.")

    @archiver.command(name="setmessageduration")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(hours="How long to keep messages in hours (0-168)")
    async def set_message_duration(self, ctx: Context, hours: int):
        """Set how long to keep archived messages."""
        try:
            if not 0 <= hours <= 168:
                await self._handle_response(ctx, "Duration must be between 0 and 168 hours (1 week).")
                return

            await self.config_manager.update_setting(ctx.guild.id, "message_duration", hours)
            await self._handle_response(ctx, f"Message duration has been set to {hours} hours.")
        except Exception as e:
            logger.error(f"Error setting message duration: {e}")
            await self._handle_response(ctx, "An error occurred while setting the message duration.")

    @archiver.command(name="settemplate")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(template="The message template to use. Available placeholders: {author}, {channel}, {original_message}")
    async def set_message_template(self, ctx: Context, template: str):
        """Set the template for archived messages."""
        try:
            if not any(
                ph in template for ph in ["{author}", "{channel}", "{original_message}"]
            ):
                await self._handle_response(
                    ctx,
                    "Template must include at least one placeholder: {author}, {channel}, or {original_message}"
                )
                return

            await self.config_manager.update_setting(
                ctx.guild.id, "message_template", template
            )
            await self._handle_response(ctx, f"Message template has been set to: {template}")
        except Exception as e:
            logger.error(f"Error setting message template: {e}")
            await self._handle_response(ctx, "An error occurred while setting the message template.")

    @archiver.command(name="setconcurrent")
    @guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(count="Number of concurrent downloads (1-5)")
    async def set_concurrent_downloads(self, ctx: Context, count: int):
        """Set the number of concurrent downloads allowed."""
        try:
            if not 1 <= count <= 5:
                await self._handle_response(ctx, "Concurrent downloads must be between 1 and 5.")
                return

            await self.config_manager.update_setting(
                ctx.guild.id, "concurrent_downloads", count
            )
            await self._handle_response(ctx, f"Concurrent downloads has been set to {count}.")
        except Exception as e:
            logger.error(f"Error setting concurrent downloads: {e}")
            await self._handle_response(ctx, "An error occurred while setting concurrent downloads.")

    @archiver.command(name="settings")
    @guild_only()
    async def show_settings(self, ctx: Context):
        """Show current archiver settings."""
        try:
            # Defer the response immediately to prevent interaction timeout
            if hasattr(ctx, 'interaction') and ctx.interaction:
                await ctx.defer()
            
            embed = await self.config_manager.format_settings_embed(ctx.guild)
            
            # Use the helper method to handle the response
            await self._handle_response(ctx, embed=embed)
        except Exception as e:
            logger.error(f"Error showing settings: {e}")
            await self._handle_response(ctx, "An error occurred while showing settings.")

    @archiver.command(name="queue")
    @guild_only()
    async def show_queue(self, ctx: Context):
        """Show the current video processing queue."""
        await self.processor.show_queue_details(ctx)

    async def cog_command_error(self, ctx: Context, error: Exception) -> None:
        """Handle command errors"""
        error_msg = None
        try:
            if isinstance(error, MissingPermissions):
                error_msg = "❌ You don't have permission to use this command."
            elif isinstance(error, BotMissingPermissions):
                error_msg = "❌ I don't have the required permissions to do that."
            elif isinstance(error, MissingRequiredArgument):
                error_msg = f"❌ Missing required argument: {error.param.name}"
            elif isinstance(error, BadArgument):
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
                await self._handle_response(ctx, error_msg)

        except Exception as e:
            logger.error(f"Error handling command error: {str(e)}")
            try:
                await self._handle_response(
                    ctx,
                    "❌ An error occurred while handling another error. Please check the logs."
                )
            except Exception:
                pass

    def _init_callback(self, task: asyncio.Task) -> None:
        """Handle initialization task completion"""
        try:
            task.result()
            logger.info("Initialization completed successfully")
        except asyncio.CancelledError:
            logger.warning("Initialization was cancelled")
            asyncio.create_task(self._cleanup())
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}\n{traceback.format_exc()}")
            asyncio.create_task(self._cleanup())

    async def _initialize(self) -> None:
        """Initialize all components with proper error handling"""
        try:
            # Initialize config first as other components depend on it
            config = Config.get_conf(self, identifier=855847, force_registration=True)
            config.register_guild(**self.default_guild_settings)
            self.config_manager = ConfigManager(config)
            logger.info("Config manager initialized")

            # Set up paths
            self.data_path = Path(data_manager.cog_data_path(self))
            self.download_path = self.data_path / "downloads"
            self.download_path.mkdir(parents=True, exist_ok=True)
            logger.info("Paths initialized")

            # Clean existing downloads
            try:
                await cleanup_downloads(str(self.download_path))
            except Exception as e:
                logger.warning(f"Download cleanup error: {e}")

            # Initialize shared FFmpeg manager
            self.ffmpeg_mgr = FFmpegManager()

            # Initialize queue manager
            queue_path = self.data_path / "queue_state.json"
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            self.queue_manager = EnhancedVideoQueueManager(
                max_retries=3,
                retry_delay=5,
                max_queue_size=1000,
                cleanup_interval=1800,
                max_history_age=86400,
                persistence_path=str(queue_path),
            )
            await self.queue_manager.initialize()

            # Initialize processor
            self.processor = VideoProcessor(
                self.bot,
                self.config_manager,
                self.components,
                queue_manager=self.queue_manager,
                ffmpeg_mgr=self.ffmpeg_mgr,
                db=self.db,
            )

            # Initialize components for existing guilds
            for guild in self.bot.guilds:
                try:
                    await initialize_guild_components(self, guild.id)
                except Exception as e:
                    logger.error(f"Failed to initialize guild {guild.id}: {str(e)}")
                    continue

            # Initialize update checker
            self.update_checker = UpdateChecker(self.bot, self.config_manager)
            await self.update_checker.start()

            # Start queue processing as a background task
            self._queue_task = asyncio.create_task(
                self.queue_manager.process_queue(self.processor.process_video)
            )

            # Set ready flag
            self.ready.set()
            logger.info("VideoArchiver initialization completed successfully")

        except Exception as e:
            logger.error(f"Error during initialization: {str(e)}")
            await self._cleanup()
            raise

    async def cog_load(self) -> None:
        """Handle cog loading without blocking"""
        try:
            # Start initialization as background task without waiting
            self._init_task = asyncio.create_task(self._initialize())
            self._init_task.add_done_callback(self._init_callback)
            logger.info("Initialization started in background")
        except Exception as e:
            # Ensure cleanup on any error
            try:
                await asyncio.wait_for(
                    force_cleanup_resources(self), timeout=CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error("Force cleanup during load error timed out")
            raise ProcessingError(f"Error during cog load: {str(e)}")

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded with proper timeout handling"""
        self._unloading = True
        try:
            # Cancel any pending tasks
            if self._init_task and not self._init_task.done():
                self._init_task.cancel()

            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()

            # Cancel queue processing task if it exists
            if (
                hasattr(self, "_queue_task")
                and self._queue_task
                and not self._queue_task.done()
            ):
                self._queue_task.cancel()
                try:
                    await self._queue_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling queue task: {e}")

            # Try normal cleanup first
            cleanup_task = asyncio.create_task(cleanup_resources(self))
            try:
                await asyncio.wait_for(cleanup_task, timeout=UNLOAD_TIMEOUT)
                logger.info("Normal cleanup completed")
            except (asyncio.TimeoutError, Exception) as e:
                if isinstance(e, asyncio.TimeoutError):
                    logger.warning("Normal cleanup timed out, forcing cleanup")
                else:
                    logger.error(f"Error during normal cleanup: {str(e)}")

                # Cancel normal cleanup and force cleanup
                cleanup_task.cancel()
                try:
                    # Force cleanup with timeout
                    await asyncio.wait_for(
                        force_cleanup_resources(self), timeout=CLEANUP_TIMEOUT
                    )
                    logger.info("Force cleanup completed")
                except asyncio.TimeoutError:
                    logger.error("Force cleanup timed out")
                except Exception as e:
                    logger.error(f"Error during force cleanup: {str(e)}")

        except Exception as e:
            logger.error(f"Error during cog unload: {str(e)}")
        finally:
            self._unloading = False
            # Ensure ready flag is cleared
            self.ready.clear()
            # Clear all references
            self.bot = None
            self.processor = None
            self.queue_manager = None
            self.update_checker = None
            self.ffmpeg_mgr = None
            self.components.clear()
            self.db = None
            self._init_task = None
            self._cleanup_task = None
            if hasattr(self, "_queue_task"):
                self._queue_task = None

    async def _cleanup(self) -> None:
        """Clean up all resources with proper handling"""
        try:
            await asyncio.wait_for(cleanup_resources(self), timeout=CLEANUP_TIMEOUT)
            logger.info("Cleanup completed successfully")
        except asyncio.TimeoutError:
            logger.warning("Cleanup timed out, forcing cleanup")
            try:
                await asyncio.wait_for(
                    force_cleanup_resources(self), timeout=CLEANUP_TIMEOUT
                )
                logger.info("Force cleanup completed")
            except asyncio.TimeoutError:
                logger.error("Force cleanup timed out")
