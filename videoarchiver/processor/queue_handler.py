"""Queue processing and video handling operations"""

import os
import logging
import asyncio
import discord
from typing import Dict, Optional, Tuple, Any
from datetime import datetime

from .reactions import REACTIONS
from .progress_tracker import ProgressTracker

logger = logging.getLogger("VideoArchiver")

class QueueHandler:
    """Handles queue processing and video operations"""

    def __init__(self, bot, config_manager, components, db=None):
        self.bot = bot
        self.config_manager = config_manager
        self.components = components
        self.db = db
        self._unloading = False
        self._active_downloads: Dict[str, asyncio.Task] = {}
        self._active_downloads_lock = asyncio.Lock()
        self.progress_tracker = ProgressTracker()

    async def process_video(self, item) -> Tuple[bool, Optional[str]]:
        """Process a video from the queue"""
        if self._unloading:
            return False, "Processor is unloading"

        file_path = None
        original_message = None
        download_task = None

        try:
            # Check if video is already archived
            if self.db and self.db.is_url_archived(item.url):
                logger.info(f"Video already archived: {item.url}")
                if original_message := await self._get_original_message(item):
                    await original_message.add_reaction(REACTIONS["success"])
                    archived_info = self.db.get_archived_video(item.url)
                    if archived_info:
                        await original_message.reply(f"This video was already archived. You can find it here: {archived_info[0]}")
                return True, None

            guild_id = item.guild_id
            if guild_id not in self.components:
                return False, f"No components found for guild {guild_id}"

            components = self.components[guild_id]
            downloader = components.get("downloader")
            message_manager = components.get("message_manager")

            if not downloader or not message_manager:
                return False, f"Missing required components for guild {guild_id}"

            # Get original message and update reactions
            original_message = await self._get_original_message(item)
            if original_message:
                await original_message.remove_reaction(REACTIONS["queued"], self.bot.user)
                await original_message.add_reaction(REACTIONS["processing"])
                logger.info(f"Started processing message {item.message_id}")

            # Create progress callback
            progress_callback = self._create_progress_callback(original_message, item.url)

            # Download video
            success, file_path, error = await self._download_video(
                downloader, item.url, progress_callback
            )
            if not success:
                if original_message:
                    await original_message.add_reaction(REACTIONS["error"])
                    logger.error(f"Download failed for message {item.message_id}: {error}")
                return False, f"Failed to download video: {error}"

            # Archive video
            success, error = await self._archive_video(
                guild_id, original_message, message_manager, item.url, file_path
            )
            if not success:
                return False, error

            return True, None

        except Exception as e:
            logger.error(f"Error processing video: {str(e)}", exc_info=True)
            return False, str(e)
        finally:
            # Clean up downloaded file
            if file_path and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                except Exception as e:
                    logger.error(f"Failed to clean up file {file_path}: {e}")

    async def _archive_video(self, guild_id: int, original_message: Optional[discord.Message],
                           message_manager, url: str, file_path: str) -> Tuple[bool, Optional[str]]:
        """Archive downloaded video"""
        try:
            # Get archive channel
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return False, f"Guild {guild_id} not found"

            archive_channel = await self.config_manager.get_channel(guild, "archive")
            if not archive_channel:
                return False, "Archive channel not configured"

            # Format message
            try:
                author = original_message.author if original_message else None
                channel = original_message.channel if original_message else None
                message = await message_manager.format_message(
                    author=author, channel=channel, url=url
                )
            except Exception as e:
                return False, f"Failed to format message: {str(e)}"

            # Upload to archive channel
            if not os.path.exists(file_path):
                return False, "Processed file not found"

            archive_message = await archive_channel.send(content=message, file=discord.File(file_path))

            # Store in database if available
            if self.db and archive_message.attachments:
                discord_url = archive_message.attachments[0].url
                self.db.add_archived_video(
                    url,
                    discord_url,
                    archive_message.id,
                    archive_channel.id,
                    guild_id
                )
                logger.info(f"Added video to archive database: {url} -> {discord_url}")

            if original_message:
                await original_message.remove_reaction(REACTIONS["processing"], self.bot.user)
                await original_message.add_reaction(REACTIONS["success"])
                logger.info(f"Successfully processed message {original_message.id}")

            return True, None

        except discord.HTTPException as e:
            if original_message:
                await original_message.add_reaction(REACTIONS["error"])
            logger.error(f"Failed to upload to Discord: {str(e)}")
            return False, f"Failed to upload to Discord: {str(e)}"
        except Exception as e:
            if original_message:
                await original_message.add_reaction(REACTIONS["error"])
            logger.error(f"Failed to archive video: {str(e)}")
            return False, f"Failed to archive video: {str(e)}"

    async def _get_original_message(self, item) -> Optional[discord.Message]:
        """Retrieve the original message"""
        try:
            channel = self.bot.get_channel(item.channel_id)
            if not channel:
                return None
            return await channel.fetch_message(item.message_id)
        except discord.NotFound:
            return None
        except Exception as e:
            logger.error(f"Error fetching original message: {e}")
            return None

    def _create_progress_callback(self, message: Optional[discord.Message], url: str):
        """Create progress callback function for download tracking"""
        def progress_callback(progress: float) -> None:
            if message:
                try:
                    loop = asyncio.get_running_loop()
                    if not loop.is_running():
                        logger.warning("Event loop is not running, skipping progress update")
                        return

                    # Update progress tracking
                    self.progress_tracker.update_download_progress(url, {
                        'percent': progress,
                        'last_update': datetime.utcnow().isoformat()
                    })

                    # Create task to update reaction
                    asyncio.run_coroutine_threadsafe(
                        self._update_download_progress_reaction(message, progress),
                        loop
                    )
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")
        return progress_callback

    async def _download_video(self, downloader, url: str, progress_callback) -> Tuple[bool, Optional[str], Optional[str]]:
        """Download video with progress tracking"""
        download_task = asyncio.create_task(
            downloader.download_video(url, progress_callback=progress_callback)
        )

        async with self._active_downloads_lock:
            self._active_downloads[url] = download_task

        try:
            success, file_path, error = await download_task
            if success:
                self.progress_tracker.complete_download(url)
            else:
                self.progress_tracker.increment_download_retries(url)
            return success, file_path, error
        except asyncio.CancelledError:
            logger.info(f"Download cancelled for {url}")
            return False, None, "Download cancelled"
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return False, None, f"Download error: {str(e)}"
        finally:
            async with self._active_downloads_lock:
                self._active_downloads.pop(url, None)

    async def cleanup(self):
        """Clean up resources and stop processing"""
        try:
            logger.info("Starting QueueHandler cleanup...")
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

            logger.info("QueueHandler cleanup completed successfully")

        except Exception as e:
            logger.error(f"Error during QueueHandler cleanup: {str(e)}", exc_info=True)
            raise

    async def force_cleanup(self):
        """Force cleanup of resources when normal cleanup fails"""
        try:
            logger.info("Starting force cleanup of QueueHandler...")
            self._unloading = True

            # Force cancel all active downloads
            for url, task in list(self._active_downloads.items()):
                if not task.done():
                    task.cancel()
            self._active_downloads.clear()

            logger.info("QueueHandler force cleanup completed")

        except Exception as e:
            logger.error(f"Error during QueueHandler force cleanup: {str(e)}", exc_info=True)

    async def _update_download_progress_reaction(self, message: discord.Message, progress: float):
        """Update download progress reaction on message"""
        if not message:
            return

        try:
            # Remove old reactions
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
