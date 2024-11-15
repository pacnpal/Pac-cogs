"""Enhanced queue manager for video processing"""

import asyncio
import logging
from typing import Dict, Optional, Set, Tuple, Callable, Any, List
from datetime import datetime

from .models import QueueItem, QueueMetrics
from .persistence import QueuePersistenceManager, QueueError
from .monitoring import QueueMonitor, MonitoringError
from .cleanup import QueueCleaner, CleanupError

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("QueueManager")

class EnhancedVideoQueueManager:
    """Enhanced queue manager with improved memory management and performance"""

    def __init__(
        self,
        max_retries: int = 3,
        retry_delay: int = 5,
        max_queue_size: int = 1000,
        cleanup_interval: int = 3600,  # 1 hour
        max_history_age: int = 86400,  # 24 hours
        persistence_path: Optional[str] = None,
        backup_interval: int = 300,  # 5 minutes
        deadlock_threshold: int = 900,  # 15 minutes
    ):
        # Configuration
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_queue_size = max_queue_size
        
        # Queue storage
        self._queue: List[QueueItem] = []
        self._processing: Dict[str, QueueItem] = {}
        self._completed: Dict[str, QueueItem] = {}
        self._failed: Dict[str, QueueItem] = {}

        # Tracking
        self._guild_queues: Dict[int, Set[str]] = {}
        self._channel_queues: Dict[int, Set[str]] = {}
        self._active_tasks: Set[asyncio.Task] = set()
        
        # Locks
        self._queue_lock = asyncio.Lock()
        self._processing_lock = asyncio.Lock()
        
        # State
        self._shutdown = False
        self.metrics = QueueMetrics()

        # Components
        self.persistence = QueuePersistenceManager(persistence_path) if persistence_path else None
        self.monitor = QueueMonitor(
            deadlock_threshold=deadlock_threshold,
            max_retries=max_retries
        )
        self.cleaner = QueueCleaner(
            cleanup_interval=cleanup_interval,
            max_history_age=max_history_age
        )

        # Initialize tasks
        self._init_tasks()

    def _init_tasks(self) -> None:
        """Initialize background tasks"""
        # Start monitoring
        monitor_task = asyncio.create_task(
            self.monitor.start_monitoring(
                self._queue,
                self._processing,
                self.metrics,
                self._processing_lock
            )
        )
        self._active_tasks.add(monitor_task)

        # Start cleanup
        cleanup_task = asyncio.create_task(
            self.cleaner.start_cleanup(
                self._queue,
                self._completed,
                self._failed,
                self._guild_queues,
                self._channel_queues,
                self._processing,
                self.metrics,
                self._queue_lock
            )
        )
        self._active_tasks.add(cleanup_task)

        # Load persisted state if available
        if self.persistence:
            self._load_persisted_state()

    def _load_persisted_state(self) -> None:
        """Load persisted queue state"""
        try:
            state = self.persistence.load_queue_state()
            if state:
                self._queue = state["queue"]
                self._processing = state["processing"]
                self._completed = state["completed"]
                self._failed = state["failed"]

                # Update metrics
                metrics_data = state.get("metrics", {})
                self.metrics.total_processed = metrics_data.get("total_processed", 0)
                self.metrics.total_failed = metrics_data.get("total_failed", 0)
                self.metrics.avg_processing_time = metrics_data.get("avg_processing_time", 0.0)
                self.metrics.success_rate = metrics_data.get("success_rate", 0.0)
                self.metrics.errors_by_type = metrics_data.get("errors_by_type", {})
                self.metrics.compression_failures = metrics_data.get("compression_failures", 0)
                self.metrics.hardware_accel_failures = metrics_data.get("hardware_accel_failures", 0)

        except Exception as e:
            logger.error(f"Failed to load persisted state: {e}")

    async def process_queue(
        self,
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]]
    ) -> None:
        """Process items in the queue
        
        Args:
            processor: Function that processes queue items
        """
        logger.info("Queue processor started")
        while not self._shutdown:
            try:
                # Get next item from queue
                item = None
                async with self._queue_lock:
                    if self._queue:
                        item = self._queue.pop(0)
                        self._processing[item.url] = item
                        item.status = "processing"
                        item.processing_time = 0.0

                if not item:
                    await asyncio.sleep(1)
                    continue

                try:
                    # Process the item
                    logger.info(f"Processing queue item: {item.url}")
                    success, error = await processor(item)
                    
                    # Update metrics and status
                    async with self._processing_lock:
                        if success:
                            item.status = "completed"
                            self._completed[item.url] = item
                            logger.info(f"Successfully processed: {item.url}")
                        else:
                            item.status = "failed"
                            item.error = error
                            item.last_error = error
                            item.last_error_time = datetime.utcnow()

                            if item.retry_count < self.max_retries:
                                item.retry_count += 1
                                item.status = "pending"
                                item.last_retry = datetime.utcnow()
                                item.priority = max(0, item.priority - 1)
                                self._queue.append(item)
                                logger.warning(f"Retrying: {item.url} (attempt {item.retry_count})")
                            else:
                                self._failed[item.url] = item
                                logger.error(f"Failed after {self.max_retries} attempts: {item.url}")

                        self._processing.pop(item.url, None)

                except Exception as e:
                    logger.error(f"Error processing {item.url}: {e}")
                    async with self._processing_lock:
                        item.status = "failed"
                        item.error = str(e)
                        item.last_error = str(e)
                        item.last_error_time = datetime.utcnow()
                        self._failed[item.url] = item
                        self._processing.pop(item.url, None)

                # Persist state if enabled
                if self.persistence:
                    await self.persistence.persist_queue_state(
                        self._queue,
                        self._processing,
                        self._completed,
                        self._failed,
                        self.metrics
                    )

            except Exception as e:
                logger.error(f"Critical error in queue processor: {e}")
                await asyncio.sleep(1)

            await asyncio.sleep(0.1)

        logger.info("Queue processor stopped")

    async def add_to_queue(
        self,
        url: str,
        message_id: int,
        channel_id: int,
        guild_id: int,
        author_id: int,
        priority: int = 0,
    ) -> bool:
        """Add a video to the processing queue
        
        Args:
            url: Video URL
            message_id: Discord message ID
            channel_id: Discord channel ID
            guild_id: Discord guild ID
            author_id: Discord author ID
            priority: Queue priority (higher = higher priority)
            
        Returns:
            True if added successfully
            
        Raises:
            QueueError: If queue is full or shutting down
        """
        if self._shutdown:
            raise QueueError("Queue manager is shutting down")

        try:
            async with self._queue_lock:
                if len(self._queue) >= self.max_queue_size:
                    raise QueueError("Queue is full")

                item = QueueItem(
                    url=url,
                    message_id=message_id,
                    channel_id=channel_id,
                    guild_id=guild_id,
                    author_id=author_id,
                    added_at=datetime.utcnow(),
                    priority=priority,
                )

                # Add to tracking
                if guild_id not in self._guild_queues:
                    self._guild_queues[guild_id] = set()
                self._guild_queues[guild_id].add(url)

                if channel_id not in self._channel_queues:
                    self._channel_queues[channel_id] = set()
                self._channel_queues[channel_id].add(url)

                # Add to queue with priority
                self._queue.append(item)
                self._queue.sort(key=lambda x: (-x.priority, x.added_at))

                if self.persistence:
                    await self.persistence.persist_queue_state(
                        self._queue,
                        self._processing,
                        self._completed,
                        self._failed,
                        self.metrics
                    )

                logger.info(f"Added to queue: {url} (priority: {priority})")
                return True

        except Exception as e:
            logger.error(f"Error adding to queue: {e}")
            raise QueueError(f"Failed to add to queue: {str(e)}")

    def get_queue_status(self, guild_id: int) -> dict:
        """Get current queue status for a guild
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Dict containing queue status and metrics
        """
        try:
            pending = len([item for item in self._queue if item.guild_id == guild_id])
            processing = len([item for item in self._processing.values() if item.guild_id == guild_id])
            completed = len([item for item in self._completed.values() if item.guild_id == guild_id])
            failed = len([item for item in self._failed.values() if item.guild_id == guild_id])

            return {
                "pending": pending,
                "processing": processing,
                "completed": completed,
                "failed": failed,
                "metrics": {
                    "total_processed": self.metrics.total_processed,
                    "total_failed": self.metrics.total_failed,
                    "success_rate": self.metrics.success_rate,
                    "avg_processing_time": self.metrics.avg_processing_time,
                    "peak_memory_usage": self.metrics.peak_memory_usage,
                    "last_cleanup": self.metrics.last_cleanup.strftime("%Y-%m-%d %H:%M:%S"),
                    "errors_by_type": self.metrics.errors_by_type,
                    "compression_failures": self.metrics.compression_failures,
                    "hardware_accel_failures": self.metrics.hardware_accel_failures,
                },
            }

        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            return {
                "pending": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0,
                "metrics": {
                    "total_processed": 0,
                    "total_failed": 0,
                    "success_rate": 0.0,
                    "avg_processing_time": 0.0,
                    "peak_memory_usage": 0.0,
                    "last_cleanup": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "errors_by_type": {},
                    "compression_failures": 0,
                    "hardware_accel_failures": 0,
                },
            }

    async def clear_guild_queue(self, guild_id: int) -> int:
        """Clear all queue items for a guild
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Number of items cleared
            
        Raises:
            QueueError: If queue is shutting down
        """
        if self._shutdown:
            raise QueueError("Queue manager is shutting down")

        try:
            cleared = await self.cleaner.clear_guild_queue(
                guild_id,
                self._queue,
                self._processing,
                self._completed,
                self._failed,
                self._guild_queues,
                self._channel_queues,
                self._queue_lock
            )

            if self.persistence:
                await self.persistence.persist_queue_state(
                    self._queue,
                    self._processing,
                    self._completed,
                    self._failed,
                    self.metrics
                )

            return cleared

        except Exception as e:
            logger.error(f"Error clearing guild queue: {e}")
            raise QueueError(f"Failed to clear guild queue: {str(e)}")

    async def cleanup(self) -> None:
        """Clean up resources and stop queue processing"""
        try:
            self._shutdown = True
            
            # Stop monitoring and cleanup tasks
            self.monitor.stop_monitoring()
            self.cleaner.stop_cleanup()

            # Cancel all active tasks
            for task in self._active_tasks:
                if not task.done():
                    task.cancel()

            await asyncio.gather(*self._active_tasks, return_exceptions=True)

            # Move processing items back to queue
            async with self._queue_lock:
                for url, item in self._processing.items():
                    if item.retry_count < self.max_retries:
                        item.status = "pending"
                        item.retry_count += 1
                        self._queue.append(item)
                    else:
                        self._failed[url] = item

                self._processing.clear()

            # Final state persistence
            if self.persistence:
                await self.persistence.persist_queue_state(
                    self._queue,
                    self._processing,
                    self._completed,
                    self._failed,
                    self.metrics
                )

            # Clear collections
            self._queue.clear()
            self._completed.clear()
            self._failed.clear()
            self._guild_queues.clear()
            self._channel_queues.clear()
            self._active_tasks.clear()

            logger.info("Queue manager cleanup completed")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            raise CleanupError(f"Failed to clean up queue manager: {str(e)}")

    def force_stop(self) -> None:
        """Force stop all queue operations immediately"""
        self._shutdown = True
        
        # Stop monitoring and cleanup
        self.monitor.stop_monitoring()
        self.cleaner.stop_cleanup()
        
        # Cancel all active tasks
        for task in self._active_tasks:
            if not task.done():
                task.cancel()

        # Move processing items back to queue
        for url, item in self._processing.items():
            if item.retry_count < self.max_retries:
                item.status = "pending"
                item.retry_count += 1
                self._queue.append(item)
            else:
                self._failed[url] = item

        self._processing.clear()
        self._active_tasks.clear()

        logger.info("Queue manager force stopped")
