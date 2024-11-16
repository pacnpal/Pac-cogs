"""Enhanced queue manager for video processing"""

import asyncio
import logging
import time
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
        deadlock_threshold: int = 300,  # 5 minutes
        check_interval: int = 60,     # 1 minute
    ):
        """Initialize queue manager"""
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
        
        # Single lock for all operations to prevent deadlocks
        self._lock = asyncio.Lock()
        
        # State
        self._shutdown = False
        self._initialized = False
        self._init_event = asyncio.Event()
        self.metrics = QueueMetrics()

        # Components
        self.persistence = QueuePersistenceManager(persistence_path) if persistence_path else None
        self.monitor = QueueMonitor(
            deadlock_threshold=deadlock_threshold,
            max_retries=max_retries,
            check_interval=check_interval
        )
        self.cleaner = QueueCleaner(
            cleanup_interval=cleanup_interval,
            max_history_age=max_history_age
        )

    async def initialize(self) -> None:
        """Initialize the queue manager components sequentially"""
        if self._initialized:
            logger.info("Queue manager already initialized")
            return

        try:
            logger.info("Starting queue manager initialization...")
            
            async with self._lock:
                # Load persisted state first if available
                if self.persistence:
                    await self._load_persisted_state()
                
                # Start monitoring task
                monitor_task = asyncio.create_task(
                    self.monitor.start_monitoring(
                        self._queue,
                        self._processing,
                        self.metrics,
                        self._lock
                    )
                )
                self._active_tasks.add(monitor_task)
                logger.info("Queue monitoring started")
                
                # Start cleanup task
                cleanup_task = asyncio.create_task(
                    self.cleaner.start_cleanup(
                        self._queue,
                        self._completed,
                        self._failed,
                        self._guild_queues,
                        self._channel_queues,
                        self._processing,
                        self.metrics,
                        self._lock
                    )
                )
                self._active_tasks.add(cleanup_task)
                logger.info("Queue cleanup started")

                # Signal initialization complete
                self._initialized = True
                self._init_event.set()
                logger.info("Queue manager initialization completed")

        except Exception as e:
            logger.error(f"Failed to initialize queue manager: {e}")
            self._shutdown = True
            raise

    async def _load_persisted_state(self) -> None:
        """Load persisted queue state"""
        try:
            state = self.persistence.load_queue_state()
            if state:
                self._queue = state["queue"]
                self._completed = state["completed"]
                self._failed = state["failed"]
                self._processing = state["processing"]

                # Update metrics
                metrics_data = state.get("metrics", {})
                self.metrics.total_processed = metrics_data.get("total_processed", 0)
                self.metrics.total_failed = metrics_data.get("total_failed", 0)
                self.metrics.avg_processing_time = metrics_data.get("avg_processing_time", 0.0)
                self.metrics.success_rate = metrics_data.get("success_rate", 0.0)
                self.metrics.errors_by_type = metrics_data.get("errors_by_type", {})
                self.metrics.compression_failures = metrics_data.get("compression_failures", 0)
                self.metrics.hardware_accel_failures = metrics_data.get("hardware_accel_failures", 0)

                logger.info("Loaded persisted queue state")
        except Exception as e:
            logger.error(f"Failed to load persisted state: {e}")

    async def process_queue(
        self,
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]]
    ) -> None:
        """Process items in the queue"""
        # Wait for initialization to complete
        await self._init_event.wait()
        
        logger.info("Queue processor started")
        last_persist_time = time.time()
        persist_interval = 60  # Persist state every 60 seconds
        
        while not self._shutdown:
            try:
                items = []
                async with self._lock:
                    # Get up to 5 items from queue
                    while len(items) < 5 and self._queue:
                        item = self._queue.pop(0)
                        items.append(item)
                        self._processing[item.url] = item
                        # Update activity timestamp
                        self.monitor.update_activity()

                if not items:
                    await asyncio.sleep(0.1)
                    continue

                # Process items concurrently
                tasks = []
                for item in items:
                    task = asyncio.create_task(self._process_item(processor, item))
                    tasks.append(task)
                
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                except asyncio.CancelledError:
                    logger.info("Queue processing cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in queue processing: {e}")

                # Persist state if interval has passed
                current_time = time.time()
                if self.persistence and (current_time - last_persist_time) >= persist_interval:
                    await self._persist_state()
                    last_persist_time = current_time

            except asyncio.CancelledError:
                logger.info("Queue processing cancelled")
                break
            except Exception as e:
                logger.error(f"Critical error in queue processor: {e}")
                await asyncio.sleep(0.1)

            await asyncio.sleep(0)

    async def _process_item(
        self,
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]],
        item: QueueItem
    ) -> None:
        """Process a single queue item"""
        try:
            logger.info(f"Processing queue item: {item.url}")
            item.start_processing()
            self.metrics.last_activity_time = time.time()
            self.monitor.update_activity()
            
            success, error = await processor(item)
            
            async with self._lock:
                item.finish_processing(success, error)
                self._processing.pop(item.url, None)
                
                if success:
                    self._completed[item.url] = item
                    logger.info(f"Successfully processed: {item.url}")
                else:
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
                
                self.metrics.update(
                    processing_time=item.processing_time,
                    success=success,
                    error=error
                )

        except Exception as e:
            logger.error(f"Error processing {item.url}: {e}")
            async with self._lock:
                item.finish_processing(False, str(e))
                self._processing.pop(item.url, None)
                self._failed[item.url] = item
                self.metrics.update(
                    processing_time=item.processing_time,
                    success=False,
                    error=str(e)
                )

    async def _persist_state(self) -> None:
        """Persist current state to storage"""
        if not self.persistence:
            return
            
        try:
            async with self._lock:
                await self.persistence.persist_queue_state(
                    self._queue,
                    self._processing,
                    self._completed,
                    self._failed,
                    self.metrics
                )
        except Exception as e:
            logger.error(f"Failed to persist state: {e}")

    async def add_to_queue(
        self,
        url: str,
        message_id: int,
        channel_id: int,
        guild_id: int,
        author_id: int,
        priority: int = 0,
    ) -> bool:
        """Add a video to the processing queue"""
        if self._shutdown:
            raise QueueError("Queue manager is shutting down")

        # Wait for initialization
        await self._init_event.wait()

        try:
            async with self._lock:
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

                if guild_id not in self._guild_queues:
                    self._guild_queues[guild_id] = set()
                self._guild_queues[guild_id].add(url)

                if channel_id not in self._channel_queues:
                    self._channel_queues[channel_id] = set()
                self._channel_queues[channel_id].add(url)

                self._queue.append(item)
                self._queue.sort(key=lambda x: (-x.priority, x.added_at))

                self.metrics.last_activity_time = time.time()
                self.monitor.update_activity()

                if self.persistence:
                    await self._persist_state()

                logger.info(f"Added to queue: {url} (priority: {priority})")
                return True

        except Exception as e:
            logger.error(f"Error adding to queue: {e}")
            raise QueueError(f"Failed to add to queue: {str(e)}")

    def get_queue_status(self, guild_id: int) -> dict:
        """Get current queue status for a guild"""
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
                    "last_activity": time.time() - self.metrics.last_activity_time,
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
                    "last_activity": 0,
                },
            }

    async def cleanup(self) -> None:
        """Clean up resources and stop queue processing"""
        try:
            self._shutdown = True
            logger.info("Starting queue manager cleanup...")
            
            # Stop monitoring and cleanup tasks
            self.monitor.stop_monitoring()
            self.cleaner.stop_cleanup()

            # Cancel all active tasks
            for task in self._active_tasks:
                if not task.done():
                    task.cancel()

            await asyncio.gather(*self._active_tasks, return_exceptions=True)

            async with self._lock:
                # Move processing items back to queue
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
                    await self._persist_state()

                # Clear collections
                self._queue.clear()
                self._completed.clear()
                self._failed.clear()
                self._guild_queues.clear()
                self._channel_queues.clear()
                self._active_tasks.clear()

            # Reset initialization state
            self._initialized = False
            self._init_event.clear()
            logger.info("Queue manager cleanup completed")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            raise CleanupError(f"Failed to clean up queue manager: {str(e)}")

    def force_stop(self) -> None:
        """Force stop all queue operations immediately"""
        self._shutdown = True
        logger.info("Force stopping queue manager...")
        
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
        
        # Reset initialization state
        self._initialized = False
        self._init_event.clear()
        logger.info("Queue manager force stopped")
