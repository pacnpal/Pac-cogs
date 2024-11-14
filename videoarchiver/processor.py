"""Video processing logic for VideoArchiver"""
import discord
import logging
import yt_dlp
import re
import os
from typing import List, Optional, Tuple, Callable, Any
import asyncio
import traceback
from datetime import datetime

from videoarchiver.utils.video_downloader import VideoDownloader
from videoarchiver.utils.file_ops import secure_delete_file, cleanup_downloads
from videoarchiver.exceptions import ProcessingError, DiscordAPIError
from videoarchiver.enhanced_queue import EnhancedVideoQueueManager

logger = logging.getLogger('VideoArchiver')

class VideoProcessor:
    """Handles video processing operations"""

    def __init__(self, bot, config_manager, components):
        self.bot = bot
        self.config = config_manager
        self.components = components
        
        # Initialize enhanced queue manager with persistence and error recovery
        queue_path = os.path.join(os.path.dirname(__file__), "data", "queue_state.json")
        self.queue_manager = EnhancedVideoQueueManager(
            max_retries=3,
            retry_delay=5,
            max_queue_size=1000,
            cleanup_interval=1800,  # 30 minutes (reduced from 1 hour for more frequent cleanup)
            max_history_age=86400,  # 24 hours
            persistence_path=queue_path
        )

        # Track failed downloads for cleanup
        self._failed_downloads = set()
        self._failed_downloads_lock = asyncio.Lock()

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
                    "warning"
                )
                return False

            # Create callback for queue processing with enhanced error handling
            async def process_callback(url: str, success: bool, error: str) -> bool:
                file_path = None
                try:
                    if not success:
                        await message.remove_reaction("⏳", self.bot.user)
                        await message.add_reaction("❌")
                        await self._log_message(
                            message.guild,
                            f"Failed to process video: {error}",
                            "error"
                        )
                        return False

                    # Download video with enhanced error handling
                    try:
                        success, file_path, error = await self.components[guild_id][
                            "downloader"
                        ].download_video(url)
                    except Exception as e:
                        logger.error(f"Download error: {traceback.format_exc()}")
                        success, file_path, error = False, None, str(e)

                    if not success:
                        await message.remove_reaction("⏳", self.bot.user)
                        await message.add_reaction("❌")
                        await self._log_message(
                            message.guild,
                            f"Failed to download video: {error}",
                            "error"
                        )
                        # Track failed download for cleanup
                        if file_path:
                            async with self._failed_downloads_lock:
                                self._failed_downloads.add(file_path)
                        return False

                    # Get channels with enhanced error handling
                    try:
                        archive_channel = await self.config.get_channel(message.guild, "archive")
                        notification_channel = await self.config.get_channel(message.guild, "notification")
                        if not notification_channel:
                            notification_channel = archive_channel

                        if not archive_channel or not notification_channel:
                            raise DiscordAPIError("Required channels not found")
                    except Exception as e:
                        await self._log_message(
                            message.guild,
                            f"Channel configuration error: {str(e)}",
                            "error"
                        )
                        return False

                    try:
                        # Upload to archive channel with original message link
                        file = discord.File(file_path)
                        archive_message = await archive_channel.send(
                            f"Original: {message.jump_url}",
                            file=file
                        )

                        # Send notification with enhanced error handling for message formatting
                        try:
                            notification_content = self.components[guild_id]["message_manager"].format_archive_message(
                                username=message.author.name,
                                channel=message.channel.name,
                                original_message=message.jump_url,
                            )
                        except Exception as e:
                            logger.error(f"Message formatting error: {str(e)}")
                            notification_content = f"Video archived from {message.author.name} in {message.channel.name}\nOriginal: {message.jump_url}"

                        notification_message = await notification_channel.send(notification_content)

                        # Schedule notification message deletion with error handling
                        try:
                            await self.components[guild_id][
                                "message_manager"
                            ].schedule_message_deletion(
                                notification_message.id, notification_message.delete
                            )
                        except Exception as e:
                            logger.error(f"Failed to schedule message deletion: {str(e)}")

                        # Update reaction to show completion
                        await message.remove_reaction("⏳", self.bot.user)
                        await message.add_reaction("✅")
                        
                        # Log processing time
                        processing_time = (datetime.utcnow() - start_time).total_seconds()
                        await self._log_message(
                            message.guild,
                            f"Successfully archived video from {message.author} (took {processing_time:.1f}s)"
                        )

                        return True

                    except discord.HTTPException as e:
                        await self._log_message(
                            message.guild,
                            f"Discord API error: {str(e)}",
                            "error"
                        )
                        await message.remove_reaction("⏳", self.bot.user)
                        await message.add_reaction("❌")
                        return False

                    finally:
                        # Always attempt to delete the file if configured
                        if settings["delete_after_repost"] and file_path:
                            try:
                                if secure_delete_file(file_path):
                                    await self._log_message(
                                        message.guild,
                                        f"Successfully deleted file: {file_path}"
                                    )
                                else:
                                    await self._log_message(
                                        message.guild,
                                        f"Failed to delete file: {file_path}",
                                        "error"
                                    )
                                    # Emergency cleanup
                                    cleanup_downloads(str(self.components[guild_id]["downloader"].download_path))
                            except Exception as e:
                                logger.error(f"File deletion error: {str(e)}")
                                # Track for later cleanup
                                async with self._failed_downloads_lock:
                                    self._failed_downloads.add(file_path)

                except Exception as e:
                    logger.error(f"Process callback error: {traceback.format_exc()}")
                    await self._log_message(
                        message.guild,
                        f"Error in process callback: {str(e)}",
                        "error"
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
                    callback=process_callback,
                    priority=priority
                )
            except Exception as e:
                logger.error(f"Queue error: {str(e)}")
                await message.remove_reaction("⏳", self.bot.user)
                await message.add_reaction("❌")
                await self._log_message(
                    message.guild,
                    f"Failed to add to queue: {str(e)}",
                    "error"
                )
                return False

            # Log queue metrics with enhanced information
            queue_status = self.queue_manager.get_queue_status(guild_id)
            await self._log_message(
                message.guild,
                f"Queue Status - Pending: {queue_status['pending']}, "
                f"Processing: {queue_status['processing']}, "
                f"Success Rate: {queue_status['metrics']['success_rate']:.2%}, "
                f"Avg Processing Time: {queue_status['metrics']['avg_processing_time']:.1f}s"
            )

            return True

        except Exception as e:
            logger.error(f"Error processing video: {traceback.format_exc()}")
            await self._log_message(
                message.guild,
                f"Error processing video: {str(e)}",
                "error"
            )
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
            if message.channel.id not in settings["monitored_channels"]:
                return

            # Find all video URLs in message with improved pattern matching
            urls = self._extract_urls(message.content)

            if urls:
                # Process each URL with priority based on position
                for i, url in enumerate(urls):
                    # First URL gets highest priority
                    priority = len(urls) - i
                    await self.process_video_url(url, message, priority)

        except Exception as e:
            logger.error(f"Error processing message: {traceback.format_exc()}")
            await self._log_message(
                message.guild,
                f"Error processing message: {str(e)}",
                "error"
            )

    def _extract_urls(self, content: str) -> List[str]:
        """Extract video URLs from message content with improved pattern matching"""
        urls = []
        try:
            with yt_dlp.YoutubeDL() as ydl:
                for ie in ydl._ies:
                    if ie._VALID_URL:
                        # Use more specific pattern matching
                        pattern = f"(?P<url>{ie._VALID_URL})"
                        matches = re.finditer(pattern, content, re.IGNORECASE)
                        urls.extend(match.group("url") for match in matches)
        except Exception as e:
            logger.error(f"URL extraction error: {str(e)}")
        return list(set(urls))  # Remove duplicates

    async def _log_message(self, guild: discord.Guild, message: str, level: str = "info"):
        """Log a message to the guild's log channel with enhanced formatting"""
        log_channel = await self.config.get_channel(guild, "log")
        if log_channel:
            try:
                # Format message with timestamp and level
                formatted_message = f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] [{level.upper()}] {message}"
                await log_channel.send(formatted_message)
            except discord.HTTPException as e:
                logger.error(f"Failed to send log message to channel: {message} ({str(e)})")
        logger.log(getattr(logging, level.upper()), message)

    async def cleanup(self):
        """Clean up resources with enhanced error handling"""
        try:
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
