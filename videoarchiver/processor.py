"""Video processing logic for VideoArchiver"""

import os
import logging
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable, Set
import traceback
from datetime import datetime

from videoarchiver.queue import EnhancedVideoQueueManager  # Updated import
from videoarchiver.utils.exceptions import (
    ProcessingError,
    ConfigurationError,
    VideoVerificationError,
    QueueError,
    FileOperationError
)
from videoarchiver.utils.video_downloader import is_video_url_pattern

logger = logging.getLogger("VideoArchiver")

# Reaction emojis
REACTIONS = {
    'queued': '📹',
    'processing': '⚙️',
    'success': '✅',
    'error': '❌',
    'numbers': ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣'],
    'progress': ['⬛', '🟨', '🟩'],
    'download': ['0️⃣', '2️⃣', '4️⃣', '6️⃣', '8️⃣', '🔟']
}

# Global queue manager instance to persist across reloads
_global_queue_manager = None

# Track detailed progress information
_download_progress: Dict[str, Dict[str, Any]] = {}
_compression_progress: Dict[str, Dict[str, Any]] = {}

class VideoProcessor:
    """Handles video processing operations"""

    def __init__(
        self,
        bot,
        config_manager,
        components,
        queue_manager=None,
        ffmpeg_mgr=None
    ):
        self.bot = bot
        self.config = config_manager
        self.components = components
        self.ffmpeg_mgr = ffmpeg_mgr

        # Track active downloads and their tasks
        self._active_downloads: Dict[str, asyncio.Task] = {}
        self._active_downloads_lock = asyncio.Lock()
        self._unloading = False

        # Use global queue manager if available
        global _global_queue_manager
        if _global_queue_manager is not None:
            self.queue_manager = _global_queue_manager
            logger.info("Using existing global queue manager")
        elif queue_manager:
            self.queue_manager = queue_manager
            _global_queue_manager = queue_manager
            logger.info("Using provided queue manager and setting as global")
        else:
            data_dir = Path(os.path.dirname(__file__)) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            queue_path = data_dir / "queue_state.json"

            self.queue_manager = EnhancedVideoQueueManager(
                max_retries=3,
                retry_delay=5,
                max_queue_size=1000,
                cleanup_interval=1800,
                max_history_age=86400,
                persistence_path=str(queue_path)
            )
            _global_queue_manager = self.queue_manager
            logger.info("Created new queue manager and set as global")

        # Start queue processing
        logger.info("Starting video processing queue...")
        self._queue_task = asyncio.create_task(self.queue_manager.process_queue(self._process_video))
        logger.info("Video processing queue started successfully")

    async def cleanup(self):
        """Clean up resources and stop processing"""
        try:
            logger.info("Starting VideoProcessor cleanup...")
            self._unloading = True

            # Cancel all active downloads
            async with self._active_downloads_lock:
                for url, task in list(self._active_downloads.items()):
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            logger.error(f"Error cancelling download task for {url}: {e}")
                self._active_downloads.clear()

            # Clean up queue manager
            if hasattr(self, 'queue_manager'):
                try:
                    await self.queue_manager.cleanup()
                except Exception as e:
                    logger.error(f"Error cleaning up queue manager: {e}")

            # Clean up FFmpeg manager
            if self.ffmpeg_mgr:
                try:
                    self.ffmpeg_mgr.kill_all_processes()
                except Exception as e:
                    logger.error(f"Error cleaning up FFmpeg manager: {e}")

            # Cancel queue processing task
            if hasattr(self, '_queue_task') and not self._queue_task.done():
                self._queue_task.cancel()
                try:
                    await self._queue_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling queue task: {e}")

            logger.info("VideoProcessor cleanup completed successfully")

        except Exception as e:
            logger.error(f"Error during VideoProcessor cleanup: {traceback.format_exc()}")
            raise ProcessingError(f"Cleanup failed: {str(e)}")

    async def force_cleanup(self):
        """Force cleanup of resources when normal cleanup fails or times out"""
        try:
            logger.info("Starting force cleanup of VideoProcessor...")
            self._unloading = True

            # Force cancel all active downloads
            for url, task in list(self._active_downloads.items()):
                if not task.done():
                    task.cancel()
            self._active_downloads.clear()

            # Force cleanup queue manager
            if hasattr(self, 'queue_manager'):
                try:
                    self.queue_manager.force_stop()
                except Exception as e:
                    logger.error(f"Error force stopping queue manager: {e}")

            # Force cleanup FFmpeg
            if self.ffmpeg_mgr:
                try:
                    self.ffmpeg_mgr.kill_all_processes()
                except Exception as e:
                    logger.error(f"Error force cleaning FFmpeg manager: {e}")

            # Force cancel queue task
            if hasattr(self, '_queue_task') and not self._queue_task.done():
                self._queue_task.cancel()

            logger.info("VideoProcessor force cleanup completed")

        except Exception as e:
            logger.error(f"Error during VideoProcessor force cleanup: {traceback.format_exc()}")
            # Don't raise here as this is the last resort cleanup

    async def process_message(self, message: discord.Message) -> None:
        """Process a message for video content"""
        try:
            # Check if message contains any video URLs
            if not message.content and not message.attachments:
                logger.debug(f"No content or attachments in message {message.id}")
                return

            # Get guild settings
            settings = await self.config.get_guild_settings(message.guild.id)
            if not settings:
                logger.warning(f"No settings found for guild {message.guild.id}")
                return

            # Log settings for debugging
            logger.debug(f"Guild {message.guild.id} settings: {settings}")

            # Check if channel is enabled
            enabled_channels = settings.get("enabled_channels", [])
            if enabled_channels and message.channel.id not in enabled_channels:
                logger.debug(f"Channel {message.channel.id} not in enabled channels: {enabled_channels}")
                return

            # Extract URLs from message content and attachments
            urls = []
            if message.content:
                # Log message content for debugging
                logger.debug(f"Processing message content: {message.content}")
                enabled_sites = settings.get("enabled_sites", [])
                logger.debug(f"Enabled sites: {enabled_sites}")

                # Add URLs from message content
                for word in message.content.split():
                    # Log each word being checked
                    logger.debug(f"Checking word: {word}")
                    # Use proper video URL validation
                    if is_video_url_pattern(word):
                        # If no sites are enabled, accept all URLs
                        # Otherwise, check if URL contains any enabled site
                        if not enabled_sites or any(site in word.lower() for site in enabled_sites):
                            logger.debug(f"Found matching URL: {word}")
                            urls.append(word)
                        else:
                            logger.debug(f"URL {word} doesn't match any enabled sites")
                    else:
                        logger.debug(f"Word {word} is not a valid video URL")

            # Add attachment URLs
            for attachment in message.attachments:
                logger.debug(f"Checking attachment: {attachment.filename}")
                if any(attachment.filename.lower().endswith(ext) for ext in ['.mp4', '.mov', '.avi', '.webm']):
                    logger.debug(f"Found video attachment: {attachment.url}")
                    urls.append(attachment.url)

            if not urls:
                logger.debug("No valid URLs found in message")
                return

            # Add each URL to the queue
            for url in urls:
                try:
                    logger.info(f"Adding URL to queue: {url}")
                    await message.add_reaction(REACTIONS['queued'])
                    await self.queue_manager.add_to_queue(
                        url=url,
                        message_id=message.id,
                        channel_id=message.channel.id,
                        guild_id=message.guild.id,
                        author_id=message.author.id,
                        priority=0
                    )
                    logger.info(f"Successfully added video to queue: {url}")
                except QueueError as e:
                    logger.error(f"Failed to add video to queue: {str(e)}")
                    await message.add_reaction(REACTIONS['error'])
                    continue

        except Exception as e:
            logger.error(f"Error processing message: {traceback.format_exc()}")
            try:
                await message.add_reaction(REACTIONS["error"])
            except:
                pass

    async def _process_video(self, item) -> Tuple[bool, Optional[str]]:
        """Process a video from the queue"""
        if self._unloading:
            return False, "Processor is unloading"

        file_path = None
        original_message = None
        download_task = None

        try:
            guild_id = item.guild_id
            if guild_id not in self.components:
                return False, f"No components found for guild {guild_id}"

            components = self.components[guild_id]
            downloader = components.get("downloader")
            message_manager = components.get("message_manager")

            if not downloader or not message_manager:
                return False, f"Missing required components for guild {guild_id}"

            try:
                channel = self.bot.get_channel(item.channel_id)
                if not channel:
                    return False, f"Channel {item.channel_id} not found"
                original_message = await channel.fetch_message(item.message_id)

                await original_message.remove_reaction(
                    REACTIONS["queued"], self.bot.user
                )
                await original_message.add_reaction(REACTIONS["processing"])
                logger.info(f"Started processing message {item.message_id}")
            except discord.NotFound:
                original_message = None
            except Exception as e:
                logger.error(f"Error fetching original message: {e}")
                original_message = None

            # Create progress callback that creates tasks directly
            def progress_callback(progress: float) -> None:
                if original_message:
                    try:
                        # Try to get the current event loop
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            # If no event loop is running in this thread,
                            # we'll use the bot's loop which we know exists
                            loop = self.bot.loop

                        if not loop.is_running():
                            logger.warning(
                                "Event loop is not running, skipping progress update"
                            )
                            return

                        # Create a task to update the reaction
                        asyncio.run_coroutine_threadsafe(
                            self.update_download_progress_reaction(
                                original_message, progress
                            ),
                            loop,
                        )
                    except Exception as e:
                        logger.error(f"Error in progress callback: {e}")

            # Create and track download task
            download_task = asyncio.create_task(
                downloader.download_video(item.url, progress_callback=progress_callback)
            )

            async with self._active_downloads_lock:
                self._active_downloads[item.url] = download_task

            try:
                success, file_path, error = await download_task
                if not success:
                    if original_message:
                        await original_message.add_reaction(REACTIONS["error"])
                        logger.error(
                            f"Download failed for message {item.message_id}: {error}"
                        )
                    return False, f"Failed to download video: {error}"
            except asyncio.CancelledError:
                logger.info(f"Download cancelled for {item.url}")
                return False, "Download cancelled"
            except Exception as e:
                if original_message:
                    await original_message.add_reaction(REACTIONS["error"])
                    logger.error(
                        f"Download error for message {item.message_id}: {str(e)}"
                    )
                return False, f"Download error: {str(e)}"
            finally:
                async with self._active_downloads_lock:
                    self._active_downloads.pop(item.url, None)

            # Get archive channel
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return False, f"Guild {guild_id} not found"

            archive_channel = await self.config.get_channel(guild, "archive")
            if not archive_channel:
                return False, "Archive channel not configured"

            # Format message
            try:
                author = original_message.author if original_message else None
                message = await message_manager.format_message(
                    author=author, channel=channel, url=item.url
                )
            except Exception as e:
                return False, f"Failed to format message: {str(e)}"

            # Upload to archive channel
            try:
                if not os.path.exists(file_path):
                    return False, "Processed file not found"

                await archive_channel.send(
                    content=message, file=discord.File(file_path)
                )

                if original_message:
                    await original_message.remove_reaction(
                        REACTIONS["processing"], self.bot.user
                    )
                    await original_message.add_reaction(REACTIONS["success"])
                    logger.info(f"Successfully processed message {item.message_id}")

                return True, None

            except discord.HTTPException as e:
                if original_message:
                    await original_message.add_reaction(REACTIONS["error"])
                    logger.error(
                        f"Failed to upload to Discord for message {item.message_id}: {str(e)}"
                    )
                return False, f"Failed to upload to Discord: {str(e)}"
            except Exception as e:
                if original_message:
                    await original_message.add_reaction(REACTIONS["error"])
                    logger.error(
                        f"Failed to archive video for message {item.message_id}: {str(e)}"
                    )
                return False, f"Failed to archive video: {str(e)}"

        except Exception as e:
            logger.error(f"Error processing video: {traceback.format_exc()}")
            return False, str(e)
        finally:
            # Clean up downloaded file
            if file_path and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                except Exception as e:
                    logger.error(f"Failed to clean up file {file_path}: {e}")

    async def update_queue_position_reaction(self, message, position):
        """Update queue position reaction"""
        try:
            for reaction in REACTIONS["numbers"]:
                try:
                    await message.remove_reaction(reaction, self.bot.user)
                except:
                    pass

            if 0 <= position < len(REACTIONS["numbers"]):
                await message.add_reaction(REACTIONS["numbers"][position])
                logger.info(
                    f"Updated queue position reaction to {position + 1} for message {message.id}"
                )
        except Exception as e:
            logger.error(f"Failed to update queue position reaction: {e}")

    async def update_progress_reaction(self, message, progress):
        """Update progress reaction based on FFmpeg progress"""
        if not message:
            return

        try:
            # Get event loop for the current context
            loop = asyncio.get_running_loop()

            # Remove old reactions in the event loop
            for reaction in REACTIONS["progress"]:
                try:
                    await message.remove_reaction(reaction, self.bot.user)
                except Exception as e:
                    logger.error(f"Failed to remove progress reaction: {e}")
                    continue

            # Add new reaction based on progress
            try:
                if progress < 33:
                    await message.add_reaction(REACTIONS["progress"][0])
                elif progress < 66:
                    await message.add_reaction(REACTIONS["progress"][1])
                else:
                    await message.add_reaction(REACTIONS["progress"][2])
            except Exception as e:
                logger.error(f"Failed to add progress reaction: {e}")

        except Exception as e:
            logger.error(f"Failed to update progress reaction: {e}")

    async def update_download_progress_reaction(self, message, progress):
        """Update download progress reaction"""
        if not message:
            return

        try:
            # Remove old reactions in the event loop
            for reaction in REACTIONS["download"]:
                try:
                    await message.remove_reaction(reaction, self.bot.user)
                except Exception as e:
                    logger.error(f"Failed to remove download reaction: {e}")
                    continue

            # Add new reaction based on progress
            try:
                if progress <= 20:
                    await message.add_reaction(REACTIONS["download"][0])
                elif progress <= 40:
                    await message.add_reaction(REACTIONS["download"][1])
                elif progress <= 60:
                    await message.add_reaction(REACTIONS["download"][2])
                elif progress <= 80:
                    await message.add_reaction(REACTIONS["download"][3])
                elif progress < 100:
                    await message.add_reaction(REACTIONS["download"][4])
                else:
                    await message.add_reaction(REACTIONS["download"][5])
            except Exception as e:
                logger.error(f"Failed to add download reaction: {e}")

        except Exception as e:
            logger.error(f"Failed to update download progress reaction: {e}")

    async def _show_queue_details(self, ctx):
        """Display detailed queue status and progress information"""
        try:
            # Get queue status
            queue_status = self.queue_manager.get_queue_status(ctx.guild.id)

            # Create embed for queue overview
            embed = discord.Embed(
                title="Queue Status Details",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow(),
            )

            # Queue statistics
            embed.add_field(
                name="Queue Statistics",
                value=f"```\n"
                f"Pending: {queue_status['pending']}\n"
                f"Processing: {queue_status['processing']}\n"
                f"Completed: {queue_status['completed']}\n"
                f"Failed: {queue_status['failed']}\n"
                f"Success Rate: {queue_status['metrics']['success_rate']:.1%}\n"
                f"Avg Processing Time: {queue_status['metrics']['avg_processing_time']:.1f}s\n"
                f"```",
                inline=False,
            )

            # Active downloads
            active_downloads = ""
            for url, progress in _download_progress.items():
                if progress.get("active", False):
                    active_downloads += (
                        f"URL: {url[:50]}...\n"
                        f"Progress: {progress.get('percent', 0):.1f}%\n"
                        f"Speed: {progress.get('speed', 'N/A')}\n"
                        f"ETA: {progress.get('eta', 'N/A')}\n"
                        f"Size: {progress.get('downloaded_bytes', 0)}/{progress.get('total_bytes', 0)} bytes\n"
                        f"Started: {progress.get('start_time', 'N/A')}\n"
                        f"Retries: {progress.get('retries', 0)}\n"
                        f"-------------------\n"
                    )

            if active_downloads:
                embed.add_field(
                    name="Active Downloads",
                    value=f"```\n{active_downloads}```",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Active Downloads",
                    value="```\nNo active downloads```",
                    inline=False,
                )

            # Active compressions
            active_compressions = ""
            for url, progress in _compression_progress.items():
                if progress.get("active", False):
                    active_compressions += (
                        f"File: {progress.get('filename', 'Unknown')}\n"
                        f"Progress: {progress.get('percent', 0):.1f}%\n"
                        f"Time Elapsed: {progress.get('elapsed_time', 'N/A')}\n"
                        f"Input Size: {progress.get('input_size', 0)} bytes\n"
                        f"Current Size: {progress.get('current_size', 0)} bytes\n"
                        f"Target Size: {progress.get('target_size', 0)} bytes\n"
                        f"Codec: {progress.get('codec', 'Unknown')}\n"
                        f"Hardware Accel: {progress.get('hardware_accel', False)}\n"
                        f"-------------------\n"
                    )

            if active_compressions:
                embed.add_field(
                    name="Active Compressions",
                    value=f"```\n{active_compressions}```",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Active Compressions",
                    value="```\nNo active compressions```",
                    inline=False,
                )

            # Error statistics
            if queue_status["metrics"]["errors_by_type"]:
                error_stats = "\n".join(
                    f"{error_type}: {count}"
                    for error_type, count in queue_status["metrics"][
                        "errors_by_type"
                    ].items()
                )
                embed.add_field(
                    name="Error Statistics",
                    value=f"```\n{error_stats}```",
                    inline=False,
                )

            # Hardware acceleration statistics
            embed.add_field(
                name="Hardware Statistics",
                value=f"```\n"
                f"Hardware Accel Failures: {queue_status['metrics']['hardware_accel_failures']}\n"
                f"Compression Failures: {queue_status['metrics']['compression_failures']}\n"
                f"Peak Memory Usage: {queue_status['metrics']['peak_memory_usage']:.1f}MB\n"
                f"```",
                inline=False,
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error showing queue details: {traceback.format_exc()}")
            await ctx.send(f"Error getting queue details: {str(e)}")
