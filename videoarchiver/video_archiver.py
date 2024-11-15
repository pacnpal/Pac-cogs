"""VideoArchiver cog for Red-DiscordBot"""

from __future__ import annotations

import discord
from redbot.core import commands, Config, data_manager, checks
from discord import app_commands
from pathlib import Path
import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import sys
import traceback

from videoarchiver.config_manager import ConfigManager
from videoarchiver.update_checker import UpdateChecker
from videoarchiver.processor import VideoProcessor
from videoarchiver.utils.video_downloader import VideoDownloader
from videoarchiver.utils.message_manager import MessageManager
from videoarchiver.utils.file_ops import cleanup_downloads
from videoarchiver.queue import EnhancedVideoQueueManager
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager
from videoarchiver.database.video_archive_db import VideoArchiveDB
from videoarchiver.processor.reactions import REACTIONS, handle_archived_reaction
from videoarchiver.utils.exceptions import (
    VideoArchiverError as ProcessingError,
    ConfigurationError as ConfigError,
    VideoVerificationError as UpdateError,
    QueueError,
    FileCleanupError as FileOperationError,
)

logger = logging.getLogger("VideoArchiver")

# Constants for timeouts
UNLOAD_TIMEOUT = 30  # seconds
CLEANUP_TIMEOUT = 15  # seconds


class VideoArchiver(commands.Cog):
    """Archive videos from Discord channels"""

    default_guild_settings = {
        "enabled": False,
        "archive_channel": None,
        "log_channel": None,
        "enabled_channels": [],
        "video_format": "mp4",
        "video_quality": "high",
        "max_file_size": 25,  # MB
        "message_duration": 30,  # seconds
        "message_template": "{author} archived a video from {channel}",
        "concurrent_downloads": 2,
        "enabled_sites": None,  # None means all sites
        "use_database": False,  # Database tracking is off by default
    }

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the cog with proper error handling"""
        self.bot = bot
        self.ready = asyncio.Event()
        self._init_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._unloading = False
        self.db = None

        # Start initialization
        self._init_task = asyncio.create_task(self._initialize())
        self._init_task.add_done_callback(self._init_callback)

    def _init_callback(self, task: asyncio.Task) -> None:
        """Handle initialization task completion"""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            asyncio.create_task(self._cleanup())

    async def _initialize(self) -> None:
        """Initialize all components with proper error handling"""
        try:
            # Initialize config first as other components depend on it
            config = Config.get_conf(self, identifier=855847, force_registration=True)
            config.register_guild(**self.default_guild_settings)
            self.config_manager = ConfigManager(config)

            # Set up paths
            self.data_path = Path(data_manager.cog_data_path(self))
            self.download_path = self.data_path / "downloads"
            self.download_path.mkdir(parents=True, exist_ok=True)

            # Clean existing downloads
            await cleanup_downloads(str(self.download_path))

            # Initialize shared FFmpeg manager
            self.ffmpeg_mgr = FFmpegManager()
            logger.info("Initialized shared FFmpeg manager")

            # Initialize components dict first
            self.components: Dict[int, Dict[str, Any]] = {}

            # Initialize components for existing guilds
            for guild in self.bot.guilds:
                try:
                    await self.initialize_guild_components(guild.id)
                except Exception as e:
                    logger.error(f"Failed to initialize guild {guild.id}: {str(e)}")
                    continue

            # Initialize queue manager after components are ready
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

            # Initialize update checker
            self.update_checker = UpdateChecker(self.bot, self.config_manager)

            # Initialize processor with queue manager and shared FFmpeg manager
            self.processor = VideoProcessor(
                self.bot,
                self.config_manager,
                self.components,
                queue_manager=self.queue_manager,
                ffmpeg_mgr=self.ffmpeg_mgr,
                db=self.db,  # Pass database to processor (None by default)
            )

            # Start update checker
            await self.update_checker.start()

            # Set ready flag
            self.ready.set()

            logger.info("VideoArchiver initialization completed successfully")

        except Exception as e:
            logger.error(
                f"Critical error during initialization: {traceback.format_exc()}"
            )
            await self._cleanup()
            raise

    @commands.hybrid_group(name="archivedb", fallback="help")
    @commands.guild_only()
    async def archivedb(self, ctx: commands.Context):
        """Manage the video archive database."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @archivedb.command(name="enable")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def enable_database(self, ctx: commands.Context):
        """Enable the video archive database."""
        try:
            current_setting = await self.config_manager.get_guild_setting(
                ctx.guild, "use_database"
            )
            if current_setting:
                await ctx.send("The video archive database is already enabled.")
                return

            # Initialize database if it's being enabled
            self.db = VideoArchiveDB(self.data_path)
            # Update processor with database
            self.processor.db = self.db
            self.processor.queue_handler.db = self.db

            await self.config_manager.set_guild_setting(ctx.guild, "use_database", True)
            await ctx.send("Video archive database has been enabled.")

        except Exception as e:
            logger.error(f"Error enabling database: {e}")
            await ctx.send("An error occurred while enabling the database.")

    @archivedb.command(name="disable")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def disable_database(self, ctx: commands.Context):
        """Disable the video archive database."""
        try:
            current_setting = await self.config_manager.get_guild_setting(
                ctx.guild, "use_database"
            )
            if not current_setting:
                await ctx.send("The video archive database is already disabled.")
                return

            # Remove database references
            self.db = None
            self.processor.db = None
            self.processor.queue_handler.db = None

            await self.config_manager.set_guild_setting(
                ctx.guild, "use_database", False
            )
            await ctx.send("Video archive database has been disabled.")

        except Exception as e:
            logger.error(f"Error disabling database: {e}")
            await ctx.send("An error occurred while disabling the database.")

    @commands.hybrid_command()
    @commands.guild_only()
    @app_commands.describe(url="The URL of the video to check")
    async def checkarchived(self, ctx: commands.Context, url: str):
        """Check if a video URL has been archived and get its Discord link if it exists."""
        try:
            if not self.db:
                await ctx.send(
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

    @commands.hybrid_group(name="archiver", fallback="help")
    @commands.guild_only()
    async def archiver(self, ctx: commands.Context):
        """Manage video archiver settings."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @archiver.command(name="enable")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def enable_archiver(self, ctx: commands.Context):
        """Enable video archiving in this server."""
        try:
            current_setting = await self.config_manager.get_guild_setting(
                ctx.guild, "enabled"
            )
            if current_setting:
                await ctx.send("Video archiving is already enabled.")
                return

            await self.config_manager.set_guild_setting(ctx.guild, "enabled", True)
            await ctx.send("Video archiving has been enabled.")

        except Exception as e:
            logger.error(f"Error enabling archiver: {e}")
            await ctx.send("An error occurred while enabling video archiving.")

    @archiver.command(name="disable")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def disable_archiver(self, ctx: commands.Context):
        """Disable video archiving in this server."""
        try:
            current_setting = await self.config_manager.get_guild_setting(
                ctx.guild, "enabled"
            )
            if not current_setting:
                await ctx.send("Video archiving is already disabled.")
                return

            await self.config_manager.set_guild_setting(ctx.guild, "enabled", False)
            await ctx.send("Video archiving has been disabled.")

        except Exception as e:
            logger.error(f"Error disabling archiver: {e}")
            await ctx.send("An error occurred while disabling video archiving.")

    @archiver.command(name="setchannel")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where archived videos will be stored")
    async def set_archive_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Set the channel where archived videos will be stored."""
        try:
            await self.config_manager.set_guild_setting(
                ctx.guild, "archive_channel", channel.id
            )
            await ctx.send(f"Archive channel has been set to {channel.mention}.")
        except Exception as e:
            logger.error(f"Error setting archive channel: {e}")
            await ctx.send("An error occurred while setting the archive channel.")

    @archiver.command(name="setlog")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel where log messages will be sent")
    async def set_log_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Set the channel where log messages will be sent."""
        try:
            await self.config_manager.set_guild_setting(
                ctx.guild, "log_channel", channel.id
            )
            await ctx.send(f"Log channel has been set to {channel.mention}.")
        except Exception as e:
            logger.error(f"Error setting log channel: {e}")
            await ctx.send("An error occurred while setting the log channel.")

    @archiver.command(name="addchannel")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to monitor for videos")
    async def add_enabled_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Add a channel to monitor for videos."""
        try:
            enabled_channels = await self.config_manager.get_guild_setting(
                ctx.guild, "enabled_channels"
            )
            if channel.id in enabled_channels:
                await ctx.send(f"{channel.mention} is already being monitored.")
                return

            enabled_channels.append(channel.id)
            await self.config_manager.set_guild_setting(
                ctx.guild, "enabled_channels", enabled_channels
            )
            await ctx.send(f"Now monitoring {channel.mention} for videos.")
        except Exception as e:
            logger.error(f"Error adding enabled channel: {e}")
            await ctx.send("An error occurred while adding the channel.")

    @archiver.command(name="removechannel")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to stop monitoring")
    async def remove_enabled_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Remove a channel from video monitoring."""
        try:
            enabled_channels = await self.config_manager.get_guild_setting(
                ctx.guild, "enabled_channels"
            )
            if channel.id not in enabled_channels:
                await ctx.send(f"{channel.mention} is not being monitored.")
                return

            enabled_channels.remove(channel.id)
            await self.config_manager.set_guild_setting(
                ctx.guild, "enabled_channels", enabled_channels
            )
            await ctx.send(f"Stopped monitoring {channel.mention} for videos.")
        except Exception as e:
            logger.error(f"Error removing enabled channel: {e}")
            await ctx.send("An error occurred while removing the channel.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Handle reactions to messages"""
        if payload.user_id == self.bot.user.id:
            return

        try:
            # Get the channel and message
            channel = self.bot.get_channel(payload.channel_id)
            if not channel:
                return
            message = await channel.fetch_message(payload.message_id)
            if not message:
                return

            # Check if it's the archived reaction
            if str(payload.emoji) == REACTIONS["archived"]:
                # Only process if database is enabled
                if self.db:
                    user = self.bot.get_user(payload.user_id)
                    await handle_archived_reaction(message, user, self.db)

        except Exception as e:
            logger.error(f"Error handling reaction: {e}")

    async def cog_load(self) -> None:
        """Handle cog loading"""
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            await self._cleanup()
            raise ProcessingError("Cog initialization timed out")
        except Exception as e:
            await self._cleanup()
            raise ProcessingError(f"Error during cog load: {str(e)}")

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded with timeout"""
        self._unloading = True
        try:
            # Create cleanup task with timeout
            cleanup_task = asyncio.create_task(self._cleanup())
            try:
                await asyncio.wait_for(cleanup_task, timeout=UNLOAD_TIMEOUT)
            except asyncio.TimeoutError:
                logger.error("Cog unload timed out, forcing cleanup")
                # Force cleanup of any remaining resources
                await self._force_cleanup()
        except Exception as e:
            logger.error(f"Error during cog unload: {str(e)}")
            await self._force_cleanup()
        finally:
            self._unloading = False

    async def _force_cleanup(self) -> None:
        """Force cleanup of resources when timeout occurs"""
        try:
            # Cancel all tasks
            if hasattr(self, "processor"):
                await self.processor.force_cleanup()

            # Force stop queue manager
            if hasattr(self, "queue_manager"):
                self.queue_manager.force_stop()

            # Kill any remaining FFmpeg processes
            if hasattr(self, "ffmpeg_mgr"):
                self.ffmpeg_mgr.kill_all_processes()

            # Clean up download directory
            if hasattr(self, "download_path") and self.download_path.exists():
                try:
                    await cleanup_downloads(str(self.download_path))
                    self.download_path.rmdir()
                except Exception as e:
                    logger.error(f"Error force cleaning download directory: {str(e)}")

        except Exception as e:
            logger.error(f"Error during force cleanup: {str(e)}")
        finally:
            self.ready.clear()

    async def _cleanup(self) -> None:
        """Clean up all resources with proper handling"""
        try:
            # Cancel initialization if still running
            if self._init_task and not self._init_task.done():
                self._init_task.cancel()
                try:
                    await asyncio.wait_for(self._init_task, timeout=CLEANUP_TIMEOUT)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

            # Stop update checker
            if hasattr(self, "update_checker"):
                try:
                    await asyncio.wait_for(
                        self.update_checker.stop(), timeout=CLEANUP_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    pass

            # Clean up processor
            if hasattr(self, "processor"):
                try:
                    await asyncio.wait_for(
                        self.processor.cleanup(), timeout=CLEANUP_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    await self.processor.force_cleanup()

            # Clean up queue manager
            if hasattr(self, "queue_manager"):
                try:
                    await asyncio.wait_for(
                        self.queue_manager.cleanup(), timeout=CLEANUP_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    self.queue_manager.force_stop()

            # Clean up components for each guild
            if hasattr(self, "components"):
                for guild_id, components in self.components.items():
                    try:
                        if "message_manager" in components:
                            await components["message_manager"].cancel_all_deletions()
                        if "downloader" in components:
                            components["downloader"] = None
                        if "ffmpeg_mgr" in components:
                            components["ffmpeg_mgr"] = None
                    except Exception as e:
                        logger.error(f"Error cleaning up guild {guild_id}: {str(e)}")

                self.components.clear()

            # Clean up download directory
            if hasattr(self, "download_path") and self.download_path.exists():
                try:
                    await cleanup_downloads(str(self.download_path))
                    self.download_path.rmdir()
                except Exception as e:
                    logger.error(f"Error cleaning up download directory: {str(e)}")

        except Exception as e:
            logger.error(f"Error during cleanup: {traceback.format_exc()}")
            raise ProcessingError(f"Cleanup failed: {str(e)}")
        finally:
            self.ready.clear()

    async def initialize_guild_components(self, guild_id: int) -> None:
        """Initialize or update components for a guild with error handling"""
        try:
            settings = await self.config_manager.get_guild_settings(guild_id)

            # Ensure download directory exists and is clean
            self.download_path.mkdir(parents=True, exist_ok=True)
            await cleanup_downloads(str(self.download_path))

            # Clean up old components if they exist
            if guild_id in self.components:
                old_components = self.components[guild_id]
                if "message_manager" in old_components:
                    await old_components["message_manager"].cancel_all_deletions()
                if "downloader" in old_components:
                    old_components["downloader"] = None

            # Initialize new components with validated settings
            self.components[guild_id] = {
                "downloader": VideoDownloader(
                    str(self.download_path),
                    settings["video_format"],
                    settings["video_quality"],
                    settings["max_file_size"],
                    settings["enabled_sites"] if settings["enabled_sites"] else None,
                    settings["concurrent_downloads"],
                    ffmpeg_mgr=self.ffmpeg_mgr,  # Use shared FFmpeg manager
                ),
                "message_manager": MessageManager(
                    settings["message_duration"], settings["message_template"]
                ),
            }

            logger.info(f"Successfully initialized components for guild {guild_id}")

        except Exception as e:
            logger.error(
                f"Failed to initialize guild {guild_id}: {traceback.format_exc()}"
            )
            raise ProcessingError(f"Guild initialization failed: {str(e)}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Handle bot joining a new guild"""
        if not self.ready.is_set():
            return

        try:
            await self.initialize_guild_components(guild.id)
            logger.info(f"Initialized components for new guild {guild.id}")
        except Exception as e:
            logger.error(f"Failed to initialize new guild {guild.id}: {str(e)}")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Handle bot leaving a guild"""
        try:
            if guild.id in self.components:
                # Clean up components
                components = self.components[guild.id]
                if "message_manager" in components:
                    await components["message_manager"].cancel_all_deletions()
                if "downloader" in components:
                    components["downloader"] = None
                if "ffmpeg_mgr" in components:
                    components["ffmpeg_mgr"] = None

                # Remove guild components
                self.components.pop(guild.id)

                logger.info(f"Cleaned up components for removed guild {guild.id}")
        except Exception as e:
            logger.error(f"Error cleaning up removed guild {guild.id}: {str(e)}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle new messages for video processing"""
        if not self.ready.is_set() or message.guild is None or message.author.bot:
            return

        try:
            await self.processor.process_message(message)
        except Exception as e:
            logger.error(
                f"Error processing message {message.id}: {traceback.format_exc()}"
            )
            try:
                log_channel = await self.config_manager.get_channel(
                    message.guild, "log"
                )
                if log_channel:
                    await log_channel.send(
                        f"Error processing message: {str(e)}\n"
                        f"Message ID: {message.id}\n"
                        f"Channel: {message.channel.mention}"
                    )
            except Exception as log_error:
                logger.error(f"Failed to log error to guild: {str(log_error)}")

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
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
