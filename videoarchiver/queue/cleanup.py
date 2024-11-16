"""Queue cleanup operations"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
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
        cleanup_interval: int = 1800,  # 30 minutes
        max_history_age: int = 43200,  # 12 hours
    ):
        self.cleanup_interval = cleanup_interval
        self.max_history_age = max_history_age
        self._shutdown = False
        self._cleanup_task: Optional[asyncio.Task] = None
        self._last_cleanup_time = datetime.utcnow()

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
        if self._cleanup_task is not None:
            logger.warning("Cleanup task already running")
            return

        logger.info("Starting queue cleanup task...")
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(
                queue,
                completed,
                failed,
                guild_queues,
                channel_queues,
                processing,
                metrics,
                queue_lock
            )
        )

    async def _cleanup_loop(
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
        """Main cleanup loop"""
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
                self._last_cleanup_time = datetime.utcnow()
                await asyncio.sleep(self.cleanup_interval)

            except asyncio.CancelledError:
                logger.info("Queue cleanup cancelled")
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {str(e)}")
                # Shorter sleep on error to retry sooner
                await asyncio.sleep(30)

    def stop_cleanup(self) -> None:
        """Stop the cleanup process"""
        logger.info("Stopping queue cleanup...")
        self._shutdown = True
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        self._cleanup_task = None

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
            items_cleaned = 0

            async with queue_lock:
                # Clean up completed items
                completed_count = len(completed)
                for url in list(completed.keys()):
                    try:
                        item = completed[url]
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
                            items_cleaned += 1
                    except Exception as e:
                        logger.error(f"Error cleaning completed item {url}: {e}")
                        completed.pop(url)
                        items_cleaned += 1

                # Clean up failed items
                failed_count = len(failed)
                for url in list(failed.keys()):
                    try:
                        item = failed[url]
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
                            items_cleaned += 1
                    except Exception as e:
                        logger.error(f"Error cleaning failed item {url}: {e}")
                        failed.pop(url)
                        items_cleaned += 1

                # Clean up guild tracking
                guild_count = len(guild_queues)
                for guild_id in list(guild_queues.keys()):
                    original_size = len(guild_queues[guild_id])
                    guild_queues[guild_id] = {
                        url for url in guild_queues[guild_id]
                        if url in queue or url in processing
                    }
                    items_cleaned += original_size - len(guild_queues[guild_id])
                    if not guild_queues[guild_id]:
                        guild_queues.pop(guild_id)

                # Clean up channel tracking
                channel_count = len(channel_queues)
                for channel_id in list(channel_queues.keys()):
                    original_size = len(channel_queues[channel_id])
                    channel_queues[channel_id] = {
                        url for url in channel_queues[channel_id]
                        if url in queue or url in processing
                    }
                    items_cleaned += original_size - len(channel_queues[channel_id])
                    if not channel_queues[channel_id]:
                        channel_queues.pop(channel_id)

                # Update metrics
                metrics.last_cleanup = current_time

                logger.info(
                    f"Queue cleanup completed:\n"
                    f"- Items cleaned: {items_cleaned}\n"
                    f"- Completed items: {completed_count} -> {len(completed)}\n"
                    f"- Failed items: {failed_count} -> {len(failed)}\n"
                    f"- Guild queues: {guild_count} -> {len(guild_queues)}\n"
                    f"- Channel queues: {channel_count} -> {len(channel_queues)}\n"
                    f"- Current queue size: {len(queue)}\n"
                    f"- Processing items: {len(processing)}"
                )

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            # Don't re-raise to keep cleanup running

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
                initial_counts = {
                    'queue': len([item for item in queue if item.guild_id == guild_id]),
                    'processing': len([item for item in processing.values() if item.guild_id == guild_id]),
                    'completed': len([item for item in completed.values() if item.guild_id == guild_id]),
                    'failed': len([item for item in failed.values() if item.guild_id == guild_id])
                }

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

                logger.info(
                    f"Cleared guild {guild_id} queue:\n"
                    f"- Queue: {initial_counts['queue']} items\n"
                    f"- Processing: {initial_counts['processing']} items\n"
                    f"- Completed: {initial_counts['completed']} items\n"
                    f"- Failed: {initial_counts['failed']} items\n"
                    f"Total cleared: {cleared_count} items"
                )
                return cleared_count

        except Exception as e:
            logger.error(f"Error clearing guild queue: {str(e)}")
            raise CleanupError(f"Failed to clear guild queue: {str(e)}")

class CleanupError(Exception):
    """Base exception for cleanup-related errors"""
    pass
