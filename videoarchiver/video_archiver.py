"""VideoArchiver cog for Red-DiscordBot"""
from __future__ import annotations

import discord
from redbot.core import commands, Config, data_manager
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
from videoarchiver.enhanced_queue import EnhancedVideoQueueManager
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager
from videoarchiver.utils.exceptions import (
    VideoArchiverError as ProcessingError,
    ConfigurationError as ConfigError,
    VideoVerificationError as UpdateError,
    QueueError,
    FileCleanupError as FileOperationError
)


logger = logging.getLogger("VideoArchiver")


class VideoArchiver(commands.Cog):
    """Archive videos from Discord channels"""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the cog with proper error handling"""
        self.bot = bot
        self.ready = asyncio.Event()
        self._init_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

        # Start initialization
        self._init_task = asyncio.create_task(self._initialize())
        self._init_task.add_done_callback(self._init_callback)

    async def _initialize(self) -> None:
        """Initialize all components with proper error handling"""
        try:
            # Initialize config first as other components depend on it
            config = Config.get_conf(self, identifier=855847, force_registration=True)
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
                    # Continue initialization even if one guild fails
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
                ffmpeg_mgr=self.ffmpeg_mgr,  # Pass shared FFmpeg manager
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
            # Clean up any partially initialized components
            await self._cleanup()
            raise

    def _init_callback(self, task: asyncio.Task) -> None:
        """Handle initialization task completion"""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            asyncio.create_task(self._cleanup())

    async def cog_load(self) -> None:
        """Handle cog loading"""
        try:
            # Wait for initialization to complete
            await asyncio.wait_for(self.ready.wait(), timeout=30)

        except asyncio.TimeoutError:
            await self._cleanup()
            raise ProcessingError("Cog initialization timed out")
        except Exception as e:
            await self._cleanup()
            raise ProcessingError(f"Error during cog load: {str(e)}")

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded"""
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up all resources"""
        try:
            # Cancel initialization if still running
            if self._init_task and not self._init_task.done():
                self._init_task.cancel()
                try:
                    await self._init_task
                except asyncio.CancelledError:
                    pass

            # Stop update checker
            if hasattr(self, "update_checker"):
                await self.update_checker.stop()

            # Clean up processor
            if hasattr(self, "processor"):
                await self.processor.cleanup()

            # Clean up queue manager
            if hasattr(self, "queue_manager"):
                await self.queue_manager.cleanup()

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
        finally:
            # Clear ready flag
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
