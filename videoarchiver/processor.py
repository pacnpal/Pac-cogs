"""Video processing logic for VideoArchiver"""

import os
import logging
import asyncio
import discord
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import traceback

from videoarchiver.enhanced_queue import EnhancedVideoQueueManager
from videoarchiver.utils.exceptions import (
    ProcessingError,
    ConfigurationError,
    VideoVerificationError,
    QueueError,
    FileOperationError
)

logger = logging.getLogger("VideoArchiver")

# Reaction emojis
REACTIONS = {
    'queued': '📹',
    'processing': '⚙️',
    'success': '✅',
    'error': '❌',
    'numbers': ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣'],  # Queue position indicators
    'progress': ['⬛', '🟨', '🟩'],  # Progress indicators (0%, 50%, 100%)
    'download': ['0️⃣', '2️⃣', '4️⃣', '6️⃣', '8️⃣', '🔟']  # Download progress (0%, 20%, 40%, 60%, 80%, 100%)
}

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

        # Start queue processing
        logger.info("Starting video processing queue...")
        self._queue_task = asyncio.create_task(self.queue_manager.process_queue(self._process_video))
        logger.info("Video processing queue started successfully")

    async def update_queue_position_reaction(self, message, position):
        """Update queue position reaction"""
        try:
            # Remove any existing number reactions
            for reaction in REACTIONS['numbers']:
                try:
                    await message.remove_reaction(reaction, self.bot.user)
                except:
                    pass
            
            # Add new position reaction if within range
            if 0 <= position < len(REACTIONS['numbers']):
                await message.add_reaction(REACTIONS['numbers'][position])
                logger.info(f"Updated queue position reaction to {position + 1} for message {message.id}")
        except Exception as e:
            logger.error(f"Failed to update queue position reaction: {e}")

    async def update_progress_reaction(self, message, progress):
        """Update progress reaction based on FFmpeg progress"""
        try:
            # Remove existing progress reactions
            for reaction in REACTIONS['progress']:
                try:
                    await message.remove_reaction(reaction, self.bot.user)
                except:
                    pass
            
            # Add appropriate progress reaction
            if progress < 33:
                await message.add_reaction(REACTIONS['progress'][0])
                logger.info(f"FFmpeg progress 0-33% for message {message.id}")
            elif progress < 66:
                await message.add_reaction(REACTIONS['progress'][1])
                logger.info(f"FFmpeg progress 33-66% for message {message.id}")
            else:
                await message.add_reaction(REACTIONS['progress'][2])
                logger.info(f"FFmpeg progress 66-100% for message {message.id}")
        except Exception as e:
            logger.error(f"Failed to update progress reaction: {e}")

    async def update_download_progress_reaction(self, message, progress):
        """Update download progress reaction"""
        try:
            # Remove existing download progress reactions
            for reaction in REACTIONS['download']:
                try:
                    await message.remove_reaction(reaction, self.bot.user)
                except:
                    pass
            
            # Add appropriate download progress reaction
            if progress <= 20:
                await message.add_reaction(REACTIONS['download'][0])
                logger.info(f"Download progress 0-20% for message {message.id}")
            elif progress <= 40:
                await message.add_reaction(REACTIONS['download'][1])
                logger.info(f"Download progress 20-40% for message {message.id}")
            elif progress <= 60:
                await message.add_reaction(REACTIONS['download'][2])
                logger.info(f"Download progress 40-60% for message {message.id}")
            elif progress <= 80:
                await message.add_reaction(REACTIONS['download'][3])
                logger.info(f"Download progress 60-80% for message {message.id}")
            elif progress < 100:
                await message.add_reaction(REACTIONS['download'][4])
                logger.info(f"Download progress 80-100% for message {message.id}")
            else:
                await message.add_reaction(REACTIONS['download'][5])
                logger.info(f"Download completed (100%) for message {message.id}")
        except Exception as e:
            logger.error(f"Failed to update download progress reaction: {e}")

    async def process_message(self, message):
        """Process a message for video content"""
        try:
            if not message.guild or not message.guild.id in self.components:
                return

            components = self.components[message.guild.id]
            downloader = components.get("downloader")
            if not downloader:
                logger.error(f"No downloader found for guild {message.guild.id}")
                return

            # Check if message contains a video URL
            content = message.content.strip()
            if not content or not downloader.is_supported_url(content):
                return

            # Add initial queued reaction
            try:
                await message.add_reaction(REACTIONS['queued'])
                logger.info(f"Added queued reaction to message {message.id}")
            except Exception as e:
                logger.error(f"Failed to add queued reaction: {e}")

            # Add to processing queue
            await self.queue_manager.add_to_queue(
                url=content,
                message_id=message.id,
                channel_id=message.channel.id,
                guild_id=message.guild.id,
                author_id=message.author.id
            )
            logger.info(f"Added message {message.id} to processing queue")

            # Update queue position
            queue_status = self.queue_manager.get_queue_status(message.guild.id)
            queue_position = queue_status['pending'] - 1  # -1 because this item was just added
            await self.update_queue_position_reaction(message, queue_position)
            logger.info(f"Message {message.id} is at position {queue_position + 1} in queue")

        except Exception as e:
            logger.error(f"Error processing message: {traceback.format_exc()}")
            raise ProcessingError(f"Failed to process message: {str(e)}")

    async def _process_video(self, item) -> Tuple[bool, Optional[str]]:
        """Process a video from the queue"""
        file_path = None
        original_message = None
        try:
            guild_id = item.guild_id
            if guild_id not in self.components:
                return False, f"No components found for guild {guild_id}"

            components = self.components[guild_id]
            downloader = components.get("downloader")
            message_manager = components.get("message_manager")

            if not downloader or not message_manager:
                return False, f"Missing required components for guild {guild_id}"

            # Get original message
            try:
                channel = self.bot.get_channel(item.channel_id)
                if not channel:
                    return False, f"Channel {item.channel_id} not found"
                original_message = await channel.fetch_message(item.message_id)
                
                # Update reactions to show processing
                await original_message.remove_reaction(REACTIONS['queued'], self.bot.user)
                await original_message.add_reaction(REACTIONS['processing'])
                logger.info(f"Started processing message {item.message_id}")
            except discord.NotFound:
                original_message = None
            except Exception as e:
                logger.error(f"Error fetching original message: {e}")
                original_message = None

            # Download and process video
            try:
                success, file_path, error = await downloader.download_video(
                    item.url,
                    progress_callback=lambda progress: self.update_download_progress_reaction(original_message, progress) if original_message else None
                )
                if not success:
                    if original_message:
                        await original_message.add_reaction(REACTIONS['error'])
                        logger.error(f"Download failed for message {item.message_id}: {error}")
                    return False, f"Failed to download video: {error}"
            except Exception as e:
                if original_message:
                    await original_message.add_reaction(REACTIONS['error'])
                    logger.error(f"Download error for message {item.message_id}: {str(e)}")
                return False, f"Download error: {str(e)}"

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
                    author=author,
                    channel=channel,
                    url=item.url
                )
            except Exception as e:
                return False, f"Failed to format message: {str(e)}"

            # Upload to archive channel
            try:
                if not os.path.exists(file_path):
                    return False, "Processed file not found"
                
                await archive_channel.send(
                    content=message,
                    file=discord.File(file_path)
                )
                
                # Update reactions for success
                if original_message:
                    await original_message.remove_reaction(REACTIONS['processing'], self.bot.user)
                    await original_message.add_reaction(REACTIONS['success'])
                    logger.info(f"Successfully processed message {item.message_id}")
                
                return True, None

            except discord.HTTPException as e:
                if original_message:
                    await original_message.add_reaction(REACTIONS['error'])
                    logger.error(f"Failed to upload to Discord for message {item.message_id}: {str(e)}")
                return False, f"Failed to upload to Discord: {str(e)}"
            except Exception as e:
                if original_message:
                    await original_message.add_reaction(REACTIONS['error'])
                    logger.error(f"Failed to archive video for message {item.message_id}: {str(e)}")
                return False, f"Failed to archive video: {str(e)}"

        except Exception as e:
            if original_message:
                await original_message.add_reaction(REACTIONS['error'])
            logger.error(f"Error processing video: {traceback.format_exc()}")
            return False, str(e)

        finally:
            # Clean up downloaded file
            if file_path and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                except Exception as e:
                    logger.error(f"Failed to clean up file {file_path}: {e}")

    async def cleanup(self):
        """Clean up resources"""
        try:
            # Cancel queue processing
            if hasattr(self, '_queue_task') and not self._queue_task.done():
                self._queue_task.cancel()
                try:
                    await self._queue_task
                except asyncio.CancelledError:
                    pass

            # Clean up queue manager
            if hasattr(self, 'queue_manager'):
                await self.queue_manager.cleanup()

            # Clean up failed downloads
            async with self._failed_downloads_lock:
                for file_path in self._failed_downloads:
                    try:
                        if os.path.exists(file_path):
                            os.unlink(file_path)
                    except Exception as e:
                        logger.error(f"Failed to clean up file {file_path}: {e}")
                self._failed_downloads.clear()

        except Exception as e:
            logger.error(f"Error during cleanup: {traceback.format_exc()}")
            raise ProcessingError(f"Cleanup failed: {str(e)}")
