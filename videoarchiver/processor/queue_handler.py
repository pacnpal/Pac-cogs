"""Queue handling functionality for video processing"""

import logging
import asyncio
import os
from enum import Enum, auto
from typing import Optional, Dict, Any, List, Tuple, Set, TypedDict, ClassVar, Callable
from datetime import datetime
import discord

from .utils import progress_tracker
from .database.video_archive_db import VideoArchiveDB
from .utils.download_manager import DownloadManager
from .utils.message_manager import MessageManager
from .utils.exceptions import QueueHandlerError
from .queue.models import QueueItem
from .config_manager import ConfigManager
from .processor.constants import REACTIONS

logger = logging.getLogger("VideoArchiver")

class QueueItemStatus(Enum):
    """Status of a queue item"""
    PENDING = auto()
    PROCESSING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()

class QueueStats(TypedDict):
    """Type definition for queue statistics"""
    active_downloads: int
    processing_items: int
    completed_items: int
    failed_items: int
    average_processing_time: float
    last_processed: Optional[str]
    is_healthy: bool

class QueueHandler:
    """Handles queue processing and video operations"""

    DOWNLOAD_TIMEOUT: ClassVar[int] = 3600  # 1 hour in seconds
    MAX_RETRIES: ClassVar[int] = 3

    def __init__(
        self,
        bot: discord.Client,
        config_manager: ConfigManager,
        components: Dict[int, Dict[str, Any]],
        db: Optional[VideoArchiveDB] = None
    ) -> None:
        self.bot = bot
        self.config_manager = config_manager
        self.components = components
        self.db = db
        self._unloading = False
        self._active_downloads: Dict[str, asyncio.Task] = {}
        self._active_downloads_lock = asyncio.Lock()
        self._stats: QueueStats = {
            "active_downloads": 0,
            "processing_items": 0,
            "completed_items": 0,
            "failed_items": 0,
            "average_processing_time": 0.0,
            "last_processed": None,
            "is_healthy": True
        }

    async def process_video(self, item: QueueItem) -> Tuple[bool, Optional[str]]:
        """
        Process a video from the queue.

        Args:
            item: Queue item to process

        Returns:
            Tuple of (success, error_message)

        Raises:
            QueueHandlerError: If there's an error during processing
        """
        if self._unloading:
            return False, "Processor is unloading"

        file_path = None
        original_message = None
        download_task = None
        start_time = datetime.utcnow()

        try:
            self._stats["processing_items"] += 1
            item.start_processing()
            logger.info(f"Started processing video: {item.url}")

            # Check if video is already archived
            if self.db and await self._check_archived_video(item):
                self._update_stats(True, start_time)
                return True, None

            # Get components
            components = await self._get_components(item.guild_id)
            downloader = components.get("downloader")
            message_manager = components.get("message_manager")

            if not downloader or not message_manager:
                raise QueueHandlerError(
                    f"Missing required components for guild {item.guild_id}"
                )

            # Get original message and update reactions
            original_message = await self._get_original_message(item)
            if original_message:
                await self._update_message_reactions(
                    original_message, QueueItemStatus.PROCESSING
                )

            # Download and archive video
            file_path = await self._process_video_file(
                downloader, message_manager, item, original_message
            )

            # Success
            self._update_stats(True, start_time)
            item.finish_processing(True)
            if original_message:
                await self._update_message_reactions(
                    original_message, QueueItemStatus.COMPLETED
                )
            return True, None

        except QueueHandlerError as e:
            logger.error(f"Queue handler error: {str(e)}")
            self._handle_processing_error(item, original_message, str(e))
            return False, str(e)
        except Exception as e:
            logger.error(f"Error processing video: {str(e)}", exc_info=True)
            self._handle_processing_error(item, original_message, str(e))
            return False, str(e)
        finally:
            await self._cleanup_file(file_path)

    async def _check_archived_video(self, item: QueueItem) -> bool:
        """Check if video is already archived and handle accordingly"""
        if not self.db:
            return False

        if self.db.is_url_archived(item.url):
            logger.info(f"Video already archived: {item.url}")
            if original_message := await self._get_original_message(item):
                await self._update_message_reactions(
                    original_message, QueueItemStatus.COMPLETED
                )
                archived_info = self.db.get_archived_video(item.url)
                if archived_info:
                    await original_message.reply(
                        f"This video was already archived. You can find it here: {archived_info[0]}"
                    )
            item.finish_processing(True)
            return True
        return False

    async def _get_components(self, guild_id: int) -> Dict[str, Any]:
        """Get required components for processing"""
        if guild_id not in self.components:
            raise QueueHandlerError(f"No components found for guild {guild_id}")
        return self.components[guild_id]

    async def _process_video_file(
        self,
        downloader: DownloadManager,
        message_manager: MessageManager,
        item: QueueItem,
        original_message: Optional[discord.Message],
    ) -> Optional[str]:
        """Download and process video file"""
        # Create progress callback
        progress_callback = self._create_progress_callback(original_message, item.url)

        # Download video
        success, file_path, error = await self._download_video(
            downloader, item.url, progress_callback
        )
        if not success:
            raise QueueHandlerError(f"Failed to download video: {error}")

        # Archive video
        success, error = await self._archive_video(
            item.guild_id, original_message, message_manager, item.url, file_path
        )
        if not success:
            raise QueueHandlerError(f"Failed to archive video: {error}")

        return file_path

    def _handle_processing_error(
        self, item: QueueItem, message: Optional[discord.Message], error: str
    ) -> None:
        """Handle processing error"""
        self._update_stats(False, datetime.utcnow())
        item.finish_processing(False, error)
        if message:
            asyncio.create_task(
                self._update_message_reactions(message, QueueItemStatus.FAILED)
            )

    def _update_stats(self, success: bool, start_time: datetime) -> None:
        """Update queue statistics"""
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        self._stats["processing_items"] -= 1
        if success:
            self._stats["completed_items"] += 1
        else:
            self._stats["failed_items"] += 1

        # Update average processing time
        total_items = self._stats["completed_items"] + self._stats["failed_items"]
        if total_items > 0:
            current_total = self._stats["average_processing_time"] * (total_items - 1)
            self._stats["average_processing_time"] = (
                current_total + processing_time
            ) / total_items

        self._stats["last_processed"] = datetime.utcnow().isoformat()

    async def _update_message_reactions(
        self, message: discord.Message, status: QueueItemStatus
    ) -> None:
        """Update message reactions based on status"""
        try:
            # Remove existing reactions
            for reaction in [
                REACTIONS["queued"],
                REACTIONS["processing"],
                REACTIONS["success"],
                REACTIONS["error"],
            ]:
                try:
                    await message.remove_reaction(reaction, self.bot.user)
                except:
                    pass

            # Add new reaction
            if status == QueueItemStatus.PROCESSING:
                await message.add_reaction(REACTIONS["processing"])
            elif status == QueueItemStatus.COMPLETED:
                await message.add_reaction(REACTIONS["success"])
            elif status == QueueItemStatus.FAILED:
                await message.add_reaction(REACTIONS["error"])
        except Exception as e:
            logger.error(f"Error updating message reactions: {e}")

    async def _cleanup_file(self, file_path: Optional[str]) -> None:
        """Clean up downloaded file"""
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except Exception as e:
                logger.error(f"Failed to clean up file {file_path}: {e}")

    async def _archive_video(
        self,
        guild_id: int,
        original_message: Optional[discord.Message],
        message_manager: MessageManager,
        url: str,
        file_path: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Archive downloaded video.

        Args:
            guild_id: Discord guild ID
            original_message: Original message containing the video
            message_manager: Message manager instance
            url: Video URL
            file_path: Path to downloaded video file

        Returns:
            Tuple of (success, error_message)

        Raises:
            QueueHandlerError: If archiving fails
        """
        try:
            # Get archive channel
            guild = self.bot.get_guild(guild_id)
            if not guild:
                raise QueueHandlerError(f"Guild {guild_id} not found")

            archive_channel = await self.config_manager.get_channel(guild, "archive")
            if not archive_channel:
                raise QueueHandlerError("Archive channel not configured")

            # Format message
            try:
                author = original_message.author if original_message else None
                channel = original_message.channel if original_message else None
                message = await message_manager.format_message(
                    author=author, channel=channel, url=url
                )
            except Exception as e:
                raise QueueHandlerError(f"Failed to format message: {str(e)}")

            # Upload to archive channel
            if not os.path.exists(file_path):
                raise QueueHandlerError("Processed file not found")

            archive_message = await archive_channel.send(
                content=message, file=discord.File(file_path)
            )

            # Store in database if available
            if self.db and archive_message.attachments:
                discord_url = archive_message.attachments[0].url
                self.db.add_archived_video(
                    url, discord_url, archive_message.id, archive_channel.id, guild_id
                )
                logger.info(f"Added video to archive database: {url} -> {discord_url}")

            return True, None

        except discord.HTTPException as e:
            logger.error(f"Failed to upload to Discord: {str(e)}")
            raise QueueHandlerError(f"Failed to upload to Discord: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to archive video: {str(e)}")
            raise QueueHandlerError(f"Failed to archive video: {str(e)}")

    async def _get_original_message(self, item: QueueItem) -> Optional[discord.Message]:
        """
        Retrieve the original message.

        Args:
            item: Queue item containing message details

        Returns:
            Original Discord message or None if not found
        """
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

    def _create_progress_callback(
        self, message: Optional[discord.Message], url: str
    ) -> Callable[[float], None]:
        """
        Create progress callback function for download tracking.

        Args:
            message: Discord message to update with progress
            url: URL being downloaded

        Returns:
            Callback function for progress updates
        """

        def progress_callback(progress: float) -> None:
            if message:
                try:
                    loop = asyncio.get_running_loop()
                    if not loop.is_running():
                        logger.warning(
                            "Event loop is not running, skipping progress update"
                        )
                        return

                    # Update progress tracking
                    progress_tracker.update_download_progress(
                        url,
                        {
                            "percent": progress,
                            "last_update": datetime.utcnow().isoformat(),
                        },
                    )

                    # Create task to update reaction
                    asyncio.run_coroutine_threadsafe(
                        self._update_download_progress_reaction(message, progress), loop
                    )
                except Exception as e:
                    logger.error(f"Error in progress callback: {e}")

        return progress_callback

    async def _download_video(
        self,
        downloader: DownloadManager,
        url: str,
        progress_callback: Callable[[float], None],
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Download video with progress tracking.

        Args:
            downloader: Download manager instance
            url: URL to download
            progress_callback: Callback for progress updates

        Returns:
            Tuple of (success, file_path, error_message)
        """
        download_task = asyncio.create_task(
            downloader.download_video(url, progress_callback=progress_callback)
        )

        async with self._active_downloads_lock:
            self._active_downloads[url] = download_task
            self._stats["active_downloads"] += 1

        try:
            success, file_path, error = await asyncio.wait_for(
                download_task, timeout=self.DOWNLOAD_TIMEOUT
            )
            if success:
                progress_tracker.complete_download(url)
            else:
                progress_tracker.increment_download_retries(url)
            return success, file_path, error

        except asyncio.TimeoutError:
            logger.error(f"Download timed out for {url}")
            return False, None, "Download timed out"
        except asyncio.CancelledError:
            logger.info(f"Download cancelled for {url}")
            return False, None, "Download cancelled"
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return False, None, f"Download error: {str(e)}"
        finally:
            async with self._active_downloads_lock:
                self._active_downloads.pop(url, None)
                self._stats["active_downloads"] -= 1

    async def cleanup(self) -> None:
        """
        Clean up resources and stop processing.

        Raises:
            QueueHandlerError: If cleanup fails
        """
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
                            logger.error(
                                f"Error cancelling download task for {url}: {e}"
                            )
                self._active_downloads.clear()
                self._stats["active_downloads"] = 0

            logger.info("QueueHandler cleanup completed successfully")

        except Exception as e:
            logger.error(f"Error during QueueHandler cleanup: {str(e)}", exc_info=True)
            raise QueueHandlerError(f"Cleanup failed: {str(e)}")

    async def force_cleanup(self) -> None:
        """Force cleanup of resources when normal cleanup fails"""
        try:
            logger.info("Starting force cleanup of QueueHandler...")
            self._unloading = True

            # Force cancel all active downloads
            for url, task in list(self._active_downloads.items()):
                if not task.done():
                    task.cancel()
            self._active_downloads.clear()
            self._stats["active_downloads"] = 0

            logger.info("QueueHandler force cleanup completed")

        except Exception as e:
            logger.error(
                f"Error during QueueHandler force cleanup: {str(e)}", exc_info=True
            )

    async def _update_download_progress_reaction(
        self, message: discord.Message, progress: float
    ) -> None:
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

    def is_healthy(self) -> bool:
        """
        Check if handler is healthy.

        Returns:
            True if handler is healthy, False otherwise
        """
        try:
            # Check if any downloads are stuck
            current_time = datetime.utcnow()
            for url, task in self._active_downloads.items():
                if not task.done() and task.get_coro().cr_frame.f_locals.get(
                    "start_time"
                ):
                    start_time = task.get_coro().cr_frame.f_locals["start_time"]
                    if (
                        current_time - start_time
                    ).total_seconds() > self.DOWNLOAD_TIMEOUT:
                        self._stats["is_healthy"] = False
                        return False

            # Check processing metrics
            if self._stats["processing_items"] > 0:
                if self._stats["average_processing_time"] > self.DOWNLOAD_TIMEOUT:
                    self._stats["is_healthy"] = False
                    return False

            self._stats["is_healthy"] = True
            return True

        except Exception as e:
            logger.error(f"Error checking health: {e}")
            self._stats["is_healthy"] = False
            return False

    def get_stats(self) -> QueueStats:
        """
        Get queue handler statistics.

        Returns:
            Dictionary containing queue statistics
        """
        return self._stats.copy()
