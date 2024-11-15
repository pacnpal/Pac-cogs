"""Video processing logic for VideoArchiver"""

import discord
import logging
import asyncio
import ffmpeg
import yt_dlp
import re
import os
from typing import Dict, List, Optional, Tuple, Callable, Any
import traceback
from datetime import datetime
from pathlib import Path

from videoarchiver.utils.video_downloader import VideoDownloader
from videoarchiver.utils.file_ops import secure_delete_file, cleanup_downloads
from videoarchiver.utils.exceptions import (
    VideoArchiverError,
    VideoDownloadError,
    VideoProcessingError,
    VideoVerificationError,
    VideoUploadError,
    VideoCleanupError,
    ConfigurationError,
    PermissionError,
    NetworkError,
    ResourceError,
    QueueError,
    ComponentError
)
from videoarchiver.ffmpeg.exceptions import (
    FFmpegError,
    CompressionError,
    VerificationError,
    FFprobeError,
    TimeoutError,
    handle_ffmpeg_error
)
from videoarchiver.enhanced_queue import EnhancedVideoQueueManager

logger = logging.getLogger("VideoArchiver")

def is_potential_url(word: str) -> bool:
    """Check if a word looks like a URL before trying yt-dlp"""
    # Check for common URL patterns
    url_patterns = [
        "http://", "https://", "www.",
        "youtu.be", "youtube.com", "vimeo.com",
        "twitch.tv", "twitter.com", "tiktok.com",
        "instagram.com", "facebook.com"
    ]
    return any(pattern in word.lower() for pattern in url_patterns)

class VideoProcessor:
    """Handles video processing operations"""

    def __init__(
        self,
        bot,
        config_manager,
        components,
        queue_manager=None
    ):
        self.bot = bot
        self.config = config_manager
        self.components = components

        # Use provided queue manager or create new one
        if queue_manager:
            self.queue_manager = queue_manager
            logger.info("Using provided queue manager")
        else:
            # Initialize enhanced queue manager with persistence and error recovery
            data_dir = Path(os.path.dirname(__file__)) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            queue_path = data_dir / "queue_state.json"
            self.queue_manager = EnhancedVideoQueueManager(
                max_retries=3,
                retry_delay=5,
                max_queue_size=1000,
                cleanup_interval=1800,  # 30 minutes
                max_history_age=86400,  # 24 hours
                persistence_path=str(queue_path)
            )
            logger.info("Created new queue manager")

        # Track failed downloads for cleanup
        self._failed_downloads = set()
        self._failed_downloads_lock = asyncio.Lock()

        # Force re-download FFmpeg binaries to ensure we have working copies
        for guild_id in self.components:
            if "ffmpeg_mgr" in self.components[guild_id]:
                try:
                    logger.info(f"Force re-downloading FFmpeg binaries for guild {guild_id}")
                    self.components[guild_id]["ffmpeg_mgr"].force_download()
                except Exception as e:
                    logger.error(f"Failed to force re-download FFmpeg: {e}")

        # Start queue processing
        logger.info("Starting video processing queue...")
        self._queue_task = asyncio.create_task(self.queue_manager.process_queue(self._process_video))
        logger.info("Video processing queue started successfully")

    async def _process_video(self, item: Any) -> Tuple[bool, Optional[str]]:
        """Process a video from the queue"""
        logger.info(f"Processing video from queue: {item.url}")
        try:
            # Get the message
            channel = self.bot.get_channel(item.channel_id)
            if not channel:
                raise ConfigurationError("Channel not found")

            try:
                message = await channel.fetch_message(item.message_id)
                if not message:
                    raise ConfigurationError("Message not found")
            except discord.NotFound:
                raise ConfigurationError("Message not found")
            except discord.Forbidden:
                raise PermissionError("Bot lacks permissions to fetch message")
            except Exception as e:
                raise NetworkError(f"Error fetching message: {str(e)}")

            guild_id = message.guild.id
            file_path = None
            start_time = datetime.utcnow()

            try:
                settings = await self.config.get_guild_settings(guild_id)
                logger.info(f"Got settings for guild {guild_id}: {settings}")

                # Download video with enhanced error handling
                try:
                    if guild_id not in self.components:
                        raise ComponentError(f"Components not initialized for guild {guild_id}")
                    
                    downloader = self.components[guild_id]["downloader"]
                    if not downloader:
                        raise ComponentError("Downloader not initialized")

                    logger.info(f"Starting download for URL: {item.url}")
                    success, file_path, error = await downloader.download_video(item.url)
                    logger.info(f"Download result: success={success}, file_path={file_path}, error={error}")
                    
                    if not success:
                        raise VideoDownloadError(error)
                        
                except (FFmpegError, CompressionError, VerificationError) as e:
                    raise VideoProcessingError(f"FFmpeg error: {str(e)}")
                except Exception as e:
                    if isinstance(e, (VideoDownloadError, VideoProcessingError)):
                        raise
                    raise VideoDownloadError(str(e))

                # Get channels with enhanced error handling
                try:
                    archive_channel = await self.config.get_channel(
                        message.guild, "archive"
                    )
                    notification_channel = await self.config.get_channel(
                        message.guild, "notification"
                    )
                    if not notification_channel:
                        notification_channel = archive_channel

                    if not archive_channel or not notification_channel:
                        raise ConfigurationError("Required channels not found")
                except Exception as e:
                    if isinstance(e, ConfigurationError):
                        raise
                    raise ConfigurationError(f"Channel configuration error: {str(e)}")

                try:
                    # Upload to archive channel with original message link
                    logger.info(f"Uploading file to archive channel: {file_path}")
                    file = discord.File(file_path)
                    archive_message = await archive_channel.send(
                        f"Original: {message.jump_url}", file=file
                    )

                    # Send notification with enhanced error handling for message formatting
                    try:
                        notification_content = self.components[guild_id][
                            "message_manager"
                        ].format_archive_message(
                            username=message.author.name,
                            channel=message.channel.name,
                            original_message=message.jump_url,
                        )
                    except Exception as e:
                        logger.error(f"Message formatting error: {str(e)}")
                        notification_content = f"Video archived from {message.author.name} in {message.channel.name}\nOriginal: {message.jump_url}"

                    notification_message = await notification_channel.send(
                        notification_content
                    )

                    # Schedule notification message deletion with error handling
                    try:
                        await self.components[guild_id][
                            "message_manager"
                        ].schedule_message_deletion(
                            notification_message.id, notification_message.delete
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to schedule message deletion: {str(e)}"
                        )

                    # Update reaction to show completion
                    await message.remove_reaction("⏳", self.bot.user)
                    await message.add_reaction("✅")

                    # Log processing time
                    processing_time = (
                        datetime.utcnow() - start_time
                    ).total_seconds()
                    await self._log_message(
                        message.guild,
                        f"Successfully archived video from {message.author} (took {processing_time:.1f}s)",
                    )

                    return True, None

                except discord.HTTPException as e:
                    raise NetworkError(f"Discord API error: {str(e)}")

                finally:
                    # Always attempt to delete the file if configured
                    if settings["delete_after_repost"] and file_path:
                        try:
                            if secure_delete_file(file_path):
                                await self._log_message(
                                    message.guild,
                                    f"Successfully deleted file: {file_path}",
                                )
                            else:
                                raise VideoCleanupError(f"Failed to delete file: {file_path}")
                        except Exception as e:
                            if not isinstance(e, VideoCleanupError):
                                e = VideoCleanupError(f"File deletion error: {str(e)}")
                            logger.error(str(e))
                            # Track for later cleanup
                            async with self._failed_downloads_lock:
                                self._failed_downloads.add(file_path)
                            raise e

            except Exception as e:
                logger.error(f"Process error: {traceback.format_exc()}")
                if not isinstance(e, VideoArchiverError):
                    e = VideoProcessingError(f"Error in process: {str(e)}")
                raise e

        except Exception as e:
            logger.error(f"Error processing video: {traceback.format_exc()}")
            error_msg = str(e)
            
            # Update message reactions based on error type
            await message.remove_reaction("⏳", self.bot.user)
            if isinstance(e, PermissionError):
                await message.add_reaction("🚫")
            elif isinstance(e, (NetworkError, ResourceError)):
                await message.add_reaction("📡")
            else:
                await message.add_reaction("❌")
            
            # Log error with appropriate level
            if isinstance(e, (ConfigurationError, ComponentError)):
                await self._log_message(message.guild, error_msg, "error")
            elif isinstance(e, (VideoDownloadError, VideoProcessingError)):
                await self._log_message(message.guild, error_msg, "warning")
            else:
                await self._log_message(message.guild, error_msg, "error")
                
            return False, error_msg

    async def process_video_url(self, url: str, message: discord.Message, priority: int = 0) -> bool:
        """Process a video URL: download, reupload, and cleanup"""
        guild_id = message.guild.id
        start_time = datetime.utcnow()

        try:
            # Add initial reactions
            await message.add_reaction("📹")
            await message.add_reaction("⏳")
            await self._log_message(message.guild, f"Processing video URL: {url}")

            settings = await self.config.get_guild_settings(guild_id)

            # Check user roles with detailed error message
            if not await self.config.check_user_roles(message.author):
                await message.remove_reaction("⏳", self.bot.user)
                await message.add_reaction("🚫")
                await self._log_message(
                    message.guild,
                    f"User {message.author} does not have required roles for video archiving",
                    "warning",
                )
                return False

            # Add to enhanced queue with priority and error handling
            try:
                await self.queue_manager.add_to_queue(
                    url=url,
                    message_id=message.id,
                    channel_id=message.channel.id,
                    guild_id=guild_id,
                    author_id=message.author.id,
                    callback=None,  # No callback needed since _process_video handles everything
                    priority=priority,
                )
            except QueueError as e:
                logger.error(f"Queue error: {str(e)}")
                await message.remove_reaction("⏳", self.bot.user)
                await message.add_reaction("❌")
                await self._log_message(
                    message.guild, f"Failed to add to queue: {str(e)}", "error"
                )
                return False

            # Log queue metrics with enhanced information
            queue_status = self.queue_manager.get_queue_status(guild_id)
            await self._log_message(
                message.guild,
                f"Queue Status - Pending: {queue_status['pending']}, "
                f"Processing: {queue_status['processing']}, "
                f"Success Rate: {queue_status['metrics']['success_rate']:.2%}, "
                f"Avg Processing Time: {queue_status['metrics']['avg_processing_time']:.1f}s",
            )

            return True

        except Exception as e:
            logger.error(f"Error processing video: {traceback.format_exc()}")
            error_msg = str(e)
            if not isinstance(e, VideoArchiverError):
                error_msg = f"Unexpected error processing video: {error_msg}"
            await self._log_message(message.guild, error_msg, "error")
            await message.remove_reaction("⏳", self.bot.user)
            await message.add_reaction("❌")
            return False

    async def process_message(self, message: discord.Message) -> None:
        """Process a message for video URLs"""
        if message.author.bot or not message.guild:
            return

        try:
            settings = await self.config.get_guild_settings(message.guild.id)

            # Check if message is in a monitored channel
            monitored_channels = settings.get("monitored_channels", [])
            if monitored_channels and message.channel.id not in monitored_channels:
                return

            # Find all video URLs in message using yt-dlp simulation
            urls = []
            try:
                if message.guild.id in self.components:
                    downloader = self.components[message.guild.id]["downloader"]
                    if not downloader:
                        raise ComponentError("Downloader not initialized")

                    # Pre-filter words that look like URLs
                    potential_urls = [
                        word for word in message.content.split()
                        if is_potential_url(word)
                    ]

                    # Only check potential URLs with yt-dlp
                    for url in potential_urls:
                        try:
                            if downloader.is_supported_url(url):
                                urls.append(url)
                        except Exception as e:
                            logger.error(f"Error checking URL {url}: {str(e)}")
                            continue

            except ComponentError as e:
                logger.error(f"Component error: {str(e)}")
                await self._log_message(
                    message.guild, f"Component error: {str(e)}", "error"
                )
                return

            if urls:
                logger.info(f"Found {len(urls)} video URLs in message {message.id}")
                # Process each URL with priority based on position
                for i, url in enumerate(urls):
                    # First URL gets highest priority
                    priority = len(urls) - i
                    logger.info(f"Processing URL {url} with priority {priority}")
                    try:
                        await self.process_video_url(url, message, priority)
                    except Exception as e:
                        logger.error(f"Error processing URL {url}: {str(e)}")
                        await self._log_message(
                            message.guild, f"Error processing URL {url}: {str(e)}", "error"
                        )
                        continue

        except Exception as e:
            error_msg = str(e)
            if not isinstance(e, VideoArchiverError):
                error_msg = f"Unexpected error processing message: {error_msg}"
            logger.error(f"Error processing message: {traceback.format_exc()}")
            await self._log_message(message.guild, error_msg, "error")

    async def _log_message(
        self, guild: discord.Guild, message: str, level: str = "info"
    ):
        """Log a message to the guild's log channel with enhanced formatting"""
        log_channel = await self.config.get_channel(guild, "log")
        if log_channel:
            try:
                # Format message with timestamp and level
                formatted_message = f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] [{level.upper()}] {message}"
                await log_channel.send(formatted_message)
            except discord.HTTPException as e:
                logger.error(
                    f"Failed to send log message to channel: {message} ({str(e)})"
                )
        logger.log(getattr(logging, level.upper()), message)

    async def cleanup(self):
        """Clean up resources with enhanced error handling"""
        try:
            # Cancel queue processing task
            if hasattr(self, "_queue_task"):
                self._queue_task.cancel()
                try:
                    await self._queue_task
                except asyncio.CancelledError:
                    pass

            # Clean up queue
            await self.queue_manager.cleanup()

            # Clean up failed downloads
            async with self._failed_downloads_lock:
                for file_path in self._failed_downloads:
                    try:
                        if os.path.exists(file_path):
                            secure_delete_file(file_path)
                    except Exception as e:
                        logger.error(f"Failed to clean up file {file_path}: {str(e)}")
                self._failed_downloads.clear()

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
