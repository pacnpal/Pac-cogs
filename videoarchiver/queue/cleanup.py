"""Queue cleanup operations"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set
from .models import QueueItem, QueueMetrics

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("QueueCleanup")

class QueueCleaner:
    """Handles cleanup of old queue items and tracking data"""

    def __init__(
        self,
        cleanup_interval: int = 3600,  # 1 hour
        max_history_age: int = 86400,  # 24 hours
    ):
        self.cleanup_interval = cleanup_interval
        self.max_history_age = max_history_age
        self._shutdown = False

    async def start_cleanup(
        self,
        queue: List[QueueItem],
        completed: Dict[str, QueueItem],
        failed: Dict[str, QueueItem],
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        processing: Dict[str, QueueItem],
        metrics: QueueMetrics,
        queue_lock: asyncio.Lock
    ) -> None:
        """Start periodic cleanup process
        
        Args:
            queue: Reference to the queue list
            completed: Reference to completed items dict
            failed: Reference to failed items dict
            guild_queues: Reference to guild tracking dict
            channel_queues: Reference to channel tracking dict
            processing: Reference to processing dict
            metrics: Reference to queue metrics
            queue_lock: Lock for queue operations
        """
        while not self._shutdown:
            try:
                await self._perform_cleanup(
                    queue,
                    completed,
                    failed,
                    guild_queues,
                    channel_queues,
                    processing,
                    metrics,
                    queue_lock
                )
                await asyncio.sleep(self.cleanup_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {str(e)}")
                await asyncio.sleep(60)

    def stop_cleanup(self) -> None:
        """Stop the cleanup process"""
        self._shutdown = True

    async def _perform_cleanup(
        self,
        queue: List[QueueItem],
        completed: Dict[str, QueueItem],
        failed: Dict[str, QueueItem],
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        processing: Dict[str, QueueItem],
        metrics: QueueMetrics,
        queue_lock: asyncio.Lock
    ) -> None:
        """Perform cleanup operations
        
        Args:
            queue: Reference to the queue list
            completed: Reference to completed items dict
            failed: Reference to failed items dict
            guild_queues: Reference to guild tracking dict
            channel_queues: Reference to channel tracking dict
            processing: Reference to processing dict
            metrics: Reference to queue metrics
            queue_lock: Lock for queue operations
        """
        try:
            current_time = datetime.utcnow()
            cleanup_cutoff = current_time - timedelta(seconds=self.max_history_age)

            async with queue_lock:
                # Clean up completed items
                for url in list(completed.keys()):
                    try:
                        item = completed[url]
                        # Ensure added_at is a datetime object
                        if not isinstance(item.added_at, datetime):
                            try:
                                if isinstance(item.added_at, str):
                                    item.added_at = datetime.fromisoformat(item.added_at)
                                else:
                                    item.added_at = current_time
                            except (ValueError, TypeError):
                                item.added_at = current_time
                        
                        if item.added_at < cleanup_cutoff:
                            completed.pop(url)
                    except Exception as e:
                        logger.error(f"Error processing completed item {url}: {e}")
                        completed.pop(url)

                # Clean up failed items
                for url in list(failed.keys()):
                    try:
                        item = failed[url]
                        # Ensure added_at is a datetime object
                        if not isinstance(item.added_at, datetime):
                            try:
                                if isinstance(item.added_at, str):
                                    item.added_at = datetime.fromisoformat(item.added_at)
                                else:
                                    item.added_at = current_time
                            except (ValueError, TypeError):
                                item.added_at = current_time
                        
                        if item.added_at < cleanup_cutoff:
                            failed.pop(url)
                    except Exception as e:
                        logger.error(f"Error processing failed item {url}: {e}")
                        failed.pop(url)

                # Clean up guild tracking
                for guild_id in list(guild_queues.keys()):
                    guild_queues[guild_id] = {
                        url for url in guild_queues[guild_id]
                        if url in queue or url in processing
                    }
                    if not guild_queues[guild_id]:
                        guild_queues.pop(guild_id)

                # Clean up channel tracking
                for channel_id in list(channel_queues.keys()):
                    channel_queues[channel_id] = {
                        url for url in channel_queues[channel_id]
                        if url in queue or url in processing
                    }
                    if not channel_queues[channel_id]:
                        channel_queues.pop(channel_id)

            metrics.last_cleanup = current_time
            logger.info("Completed periodic queue cleanup")

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            raise

    async def clear_guild_queue(
        self,
        guild_id: int,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        completed: Dict[str, QueueItem],
        failed: Dict[str, QueueItem],
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        queue_lock: asyncio.Lock
    ) -> int:
        """Clear all queue items for a specific guild
        
        Args:
            guild_id: ID of the guild to clear
            queue: Reference to the queue list
            processing: Reference to processing dict
            completed: Reference to completed items dict
            failed: Reference to failed items dict
            guild_queues: Reference to guild tracking dict
            channel_queues: Reference to channel tracking dict
            queue_lock: Lock for queue operations
            
        Returns:
            Number of items cleared
        """
        try:
            cleared_count = 0
            async with queue_lock:
                # Get URLs for this guild
                guild_urls = guild_queues.get(guild_id, set())

                # Clear from pending queue
                queue[:] = [item for item in queue if item.guild_id != guild_id]

                # Clear from processing
                for url in list(processing.keys()):
                    if processing[url].guild_id == guild_id:
                        processing.pop(url)
                        cleared_count += 1

                # Clear from completed
                for url in list(completed.keys()):
                    if completed[url].guild_id == guild_id:
                        completed.pop(url)
                        cleared_count += 1

                # Clear from failed
                for url in list(failed.keys()):
                    if failed[url].guild_id == guild_id:
                        failed.pop(url)
                        cleared_count += 1

                # Clear guild tracking
                if guild_id in guild_queues:
                    cleared_count += len(guild_queues[guild_id])
                    guild_queues.pop(guild_id)

                # Clear channel tracking for this guild's channels
                for channel_id in list(channel_queues.keys()):
                    channel_queues[channel_id] = {
                        url for url in channel_queues[channel_id]
                        if url not in guild_urls
                    }
                    if not channel_queues[channel_id]:
                        channel_queues.pop(channel_id)

            logger.info(f"Cleared {cleared_count} items from guild {guild_id} queue")
            return cleared_count

        except Exception as e:
            logger.error(f"Error clearing guild queue: {str(e)}")
            raise

class CleanupError(Exception):
    """Base exception for cleanup-related errors"""
    pass
