"""Enhanced queue system for VideoArchiver with improved memory management and performance"""

import asyncio
import logging
import json
import os
import time
import psutil
from typing import Dict, Optional, Set, Tuple, Callable, Any, List, Union
from datetime import datetime, timedelta
import traceback
from dataclasses import dataclass, asdict, field
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import tempfile
import shutil
from .exceptions import (
    QueueError,
    ResourceExhaustedError,
    ProcessingError,
    CleanupError,
    FileOperationError,
)

# Configure logging with proper format
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("EnhancedQueueManager")


@dataclass
class QueueMetrics:
    """Metrics tracking for queue performance and health"""

    total_processed: int = 0
    total_failed: int = 0
    avg_processing_time: float = 0.0
    success_rate: float = 0.0
    errors_by_type: Dict[str, int] = field(default_factory=dict)
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    last_cleanup: datetime = field(default_factory=datetime.utcnow)
    retries: int = 0
    peak_memory_usage: float = 0.0
    processing_times: List[float] = field(default_factory=list)
    compression_failures: int = 0
    hardware_accel_failures: int = 0

    def update(self, processing_time: float, success: bool, error: str = None):
        """Update metrics with new processing information"""
        self.total_processed += 1
        if not success:
            self.total_failed += 1
            if error:
                self.last_error = error
                self.last_error_time = datetime.utcnow()
                error_type = error.split(":")[0] if ":" in error else error
                self.errors_by_type[error_type] = (
                    self.errors_by_type.get(error_type, 0) + 1
                )
                
                # Track specific error types
                if "compression error" in error.lower():
                    self.compression_failures += 1
                elif "hardware acceleration failed" in error.lower():
                    self.hardware_accel_failures += 1

        # Update processing times with sliding window
        self.processing_times.append(processing_time)
        if len(self.processing_times) > 100:  # Keep last 100 processing times
            self.processing_times.pop(0)

        # Update average processing time
        self.avg_processing_time = (
            sum(self.processing_times) / len(self.processing_times)
            if self.processing_times
            else 0.0
        )

        # Update success rate
        self.success_rate = (
            (self.total_processed - self.total_failed) / self.total_processed
            if self.total_processed > 0
            else 0.0
        )

        # Update peak memory usage
        current_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        self.peak_memory_usage = max(self.peak_memory_usage, current_memory)


@dataclass
class QueueItem:
    """Represents a video processing task in the queue"""

    url: str
    message_id: int
    channel_id: int
    guild_id: int
    author_id: int
    added_at: datetime
    priority: int = 0  # Higher number = higher priority
    status: str = "pending"  # pending, processing, completed, failed
    error: Optional[str] = None
    attempt: int = 0
    _processing_time: float = 0.0  # Use private field for processing_time
    size_bytes: int = 0
    last_error: Optional[str] = None
    retry_count: int = 0
    last_retry: Optional[datetime] = None
    processing_times: List[float] = field(default_factory=list)
    last_error_time: Optional[datetime] = None
    hardware_accel_attempted: bool = False
    compression_attempted: bool = False
    original_message: Optional[Any] = None  # Store the original message reference

    @property
    def processing_time(self) -> float:
        """Get processing time as float"""
        return self._processing_time

    @processing_time.setter
    def processing_time(self, value: Any) -> None:
        """Set processing time, ensuring it's always a float"""
        try:
            if isinstance(value, str):
                self._processing_time = float(value)
            elif isinstance(value, (int, float)):
                self._processing_time = float(value)
            else:
                self._processing_time = 0.0
        except (ValueError, TypeError):
            self._processing_time = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary with datetime handling"""
        data = asdict(self)
        # Convert datetime objects to ISO format strings
        if self.added_at:
            data['added_at'] = self.added_at.isoformat()
        if self.last_retry:
            data['last_retry'] = self.last_retry.isoformat()
        if self.last_error_time:
            data['last_error_time'] = self.last_error_time.isoformat()
        # Convert _processing_time to processing_time in dict
        data['processing_time'] = self.processing_time
        data.pop('_processing_time', None)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'QueueItem':
        """Create from dictionary with datetime handling"""
        # Convert ISO format strings back to datetime objects
        if 'added_at' in data and isinstance(data['added_at'], str):
            data['added_at'] = datetime.fromisoformat(data['added_at'])
        if 'last_retry' in data and isinstance(data['last_retry'], str):
            data['last_retry'] = datetime.fromisoformat(data['last_retry'])
        if 'last_error_time' in data and isinstance(data['last_error_time'], str):
            data['last_error_time'] = datetime.fromisoformat(data['last_error_time'])
        # Handle processing_time conversion
        if 'processing_time' in data:
            try:
                if isinstance(data['processing_time'], str):
                    data['_processing_time'] = float(data['processing_time'])
                elif isinstance(data['processing_time'], (int, float)):
                    data['_processing_time'] = float(data['processing_time'])
                else:
                    data['_processing_time'] = 0.0
            except (ValueError, TypeError):
                data['_processing_time'] = 0.0
            data.pop('processing_time', None)
        return cls(**data)


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
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_queue_size = max_queue_size
        self.cleanup_interval = cleanup_interval
        self.max_history_age = max_history_age
        self.persistence_path = persistence_path
        self.backup_interval = backup_interval
        self.deadlock_threshold = deadlock_threshold

        # Queue storage with priority
        self._queue: List[QueueItem] = []
        self._queue_lock = asyncio.Lock()
        self._processing: Dict[str, QueueItem] = {}
        self._completed: Dict[str, QueueItem] = {}
        self._failed: Dict[str, QueueItem] = {}

        # Track active tasks
        self._active_tasks: Set[asyncio.Task] = set()
        self._processing_lock = asyncio.Lock()
        self._shutdown = False

        # Status tracking
        self._guild_queues: Dict[int, Set[str]] = {}
        self._channel_queues: Dict[int, Set[str]] = {}

        # Metrics tracking
        self.metrics = QueueMetrics()

        # Recovery tracking
        self._recovery_attempts: Dict[str, int] = {}
        self._last_backup: Optional[datetime] = None

        # Initialize tasks
        self._init_tasks()

    def _init_tasks(self):
        """Initialize background tasks"""
        # Cleanup and monitoring
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self._active_tasks.add(self._cleanup_task)

        # Health monitoring
        self._health_check_task = asyncio.create_task(self._monitor_health())
        self._active_tasks.add(self._health_check_task)

        # Backup task
        if self.persistence_path:
            self._backup_task = asyncio.create_task(self._periodic_backup())
            self._active_tasks.add(self._backup_task)

            # Load persisted queue
            self._load_persisted_queue()

    def force_stop(self):
        """Force stop all queue operations immediately"""
        self._shutdown = True
        
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

        # Clear task tracking
        self._active_tasks.clear()

        logger.info("Queue manager force stopped")

    async def cleanup(self):
        """Clean up resources and stop queue processing"""
        try:
            # Set shutdown flag
            self._shutdown = True

            # Cancel all monitoring tasks
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

            # Persist final state
            if self.persistence_path:
                await self._persist_queue()

            # Clear all collections
            self._queue.clear()
            self._completed.clear()
            self._failed.clear()
            self._guild_queues.clear()
            self._channel_queues.clear()
            self._active_tasks.clear()

            logger.info("Queue manager cleanup completed")

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            raise CleanupError(f"Failed to clean up queue manager: {str(e)}")

    async def process_queue(
        self, processor: Callable[[QueueItem], Tuple[bool, Optional[str]]]
    ):
        """Process items in the queue with the provided processor function"""
        logger.info("Queue processor started and waiting for items...")
        while not self._shutdown:
            try:
                # Get next item from queue
                item = None
                async with self._queue_lock:
                    if self._queue:
                        item = self._queue.pop(0)
                        self._processing[item.url] = item
                        item.status = "processing"
                        # Ensure processing_time is always a float
                        try:
                            if isinstance(item.processing_time, str):
                                # Try to convert string to float if possible
                                item.processing_time = float(item.processing_time)
                            elif not isinstance(item.processing_time, (int, float)):
                                # If not a number or convertible string, reset to 0
                                item.processing_time = 0.0
                        except (ValueError, TypeError):
                            # If conversion fails, reset to 0
                            item.processing_time = 0.0
                        # Now set the current time
                        item.processing_time = time.time()
                        logger.info(f"Processing queue item: {item.url}")

                if not item:
                    await asyncio.sleep(1)
                    continue

                try:
                    # Process the item
                    start_time = time.time()
                    logger.info(f"Calling processor for item: {item.url}")
                    success, error = await processor(item)
                    logger.info(
                        f"Processor result for {item.url}: success={success}, error={error}"
                    )
                    processing_time = time.time() - start_time

                    # Update metrics
                    self.metrics.update(processing_time, success, error)

                    # Update item status
                    async with self._processing_lock:
                        if success:
                            item.status = "completed"
                            self._completed[item.url] = item
                            logger.info(f"Successfully processed item: {item.url}")
                        else:
                            item.status = "failed"
                            item.error = error
                            item.last_error = error
                            item.last_error_time = datetime.utcnow()

                            # Handle retries with improved logic
                            if item.retry_count < self.max_retries:
                                item.retry_count += 1
                                item.status = "pending"
                                item.last_retry = datetime.utcnow()

                                # Adjust processing strategy based on error type
                                if "hardware acceleration failed" in str(error).lower():
                                    item.hardware_accel_attempted = True
                                elif "compression error" in str(error).lower():
                                    item.compression_attempted = True

                                # Add back to queue with adjusted priority
                                item.priority = max(
                                    0, item.priority - 1
                                )  # Lower priority for retries
                                self._queue.append(item)
                                logger.warning(
                                    f"Retrying item: {item.url} (attempt {item.retry_count})"
                                )
                            else:
                                self._failed[item.url] = item
                                logger.error(
                                    f"Failed to process item after {self.max_retries} attempts: {item.url}"
                                )

                        # Always remove from processing, regardless of outcome
                        self._processing.pop(item.url, None)

                except Exception as e:
                    logger.error(
                        f"Error processing item {item.url}: {traceback.format_exc()}"
                    )
                    # Ensure item is properly handled even on unexpected errors
                    async with self._processing_lock:
                        item.status = "failed"
                        item.error = str(e)
                        item.last_error = str(e)
                        item.last_error_time = datetime.utcnow()
                        self._failed[item.url] = item
                        # Always remove from processing
                        self._processing.pop(item.url, None)

                # Persist state after processing
                if self.persistence_path:
                    try:
                        await self._persist_queue()
                    except Exception as e:
                        logger.error(f"Failed to persist queue state: {e}")

            except Exception as e:
                logger.error(
                    f"Critical error in queue processor: {traceback.format_exc()}"
                )
                # Ensure we don't get stuck in a tight loop on critical errors
                await asyncio.sleep(1)
                continue  # Continue to next iteration to process remaining items

            # Small delay to prevent CPU overload
            await asyncio.sleep(0.1)

        logger.info("Queue processor stopped due to shutdown")

    async def add_to_queue(
        self,
        url: str,
        message_id: int,
        channel_id: int,
        guild_id: int,
        author_id: int,
        priority: int = 0,
    ) -> bool:
        """Add a video to the processing queue with priority support"""
        if self._shutdown:
            raise QueueError("Queue manager is shutting down")

        try:
            async with self._queue_lock:
                if len(self._queue) >= self.max_queue_size:
                    raise QueueError("Queue is full")

                # Check system resources
                if psutil.virtual_memory().percent > 90:
                    raise ResourceExhaustedError("System memory is critically low")

                # Create queue item
                item = QueueItem(
                    url=url,
                    message_id=message_id,
                    channel_id=channel_id,
                    guild_id=guild_id,
                    author_id=author_id,
                    added_at=datetime.utcnow(),
                    priority=priority,
                )

                # Add to tracking collections
                if guild_id not in self._guild_queues:
                    self._guild_queues[guild_id] = set()
                self._guild_queues[guild_id].add(url)

                if channel_id not in self._channel_queues:
                    self._channel_queues[channel_id] = set()
                self._channel_queues[channel_id].add(url)

                # Add to queue with priority
                self._queue.append(item)
                self._queue.sort(key=lambda x: (-x.priority, x.added_at))

            # Persist queue state
            if self.persistence_path:
                await self._persist_queue()

            logger.info(f"Added video to queue: {url} with priority {priority}")
            return True

        except Exception as e:
            logger.error(f"Error adding video to queue: {traceback.format_exc()}")
            raise QueueError(f"Failed to add to queue: {str(e)}")

    async def _periodic_backup(self):
        """Periodically backup queue state"""
        while not self._shutdown:
            try:
                if self.persistence_path and (
                    not self._last_backup
                    or (datetime.utcnow() - self._last_backup).total_seconds()
                    >= self.backup_interval
                ):
                    await self._persist_queue()
                    self._last_backup = datetime.utcnow()
                await asyncio.sleep(self.backup_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic backup: {str(e)}")
                await asyncio.sleep(60)

    async def _persist_queue(self):
        """Persist queue state to disk with improved error handling"""
        if not self.persistence_path:
            return

        try:
            state = {
                "queue": [item.to_dict() for item in self._queue],
                "processing": {k: v.to_dict() for k, v in self._processing.items()},
                "completed": {k: v.to_dict() for k, v in self._completed.items()},
                "failed": {k: v.to_dict() for k, v in self._failed.items()},
                "metrics": {
                    "total_processed": self.metrics.total_processed,
                    "total_failed": self.metrics.total_failed,
                    "avg_processing_time": self.metrics.avg_processing_time,
                    "success_rate": self.metrics.success_rate,
                    "errors_by_type": self.metrics.errors_by_type,
                    "last_error": self.metrics.last_error,
                    "last_error_time": (
                        self.metrics.last_error_time.isoformat()
                        if self.metrics.last_error_time
                        else None
                    ),
                    "compression_failures": self.metrics.compression_failures,
                    "hardware_accel_failures": self.metrics.hardware_accel_failures,
                },
            }

            # Ensure directory exists
            os.makedirs(os.path.dirname(self.persistence_path), exist_ok=True)

            # Write to temp file first
            temp_path = f"{self.persistence_path}.tmp"
            with open(temp_path, "w") as f:
                json.dump(state, f, default=str)
                f.flush()
                os.fsync(f.fileno())

            # Atomic rename
            os.rename(temp_path, self.persistence_path)

        except Exception as e:
            logger.error(f"Error persisting queue state: {traceback.format_exc()}")
            raise QueueError(f"Failed to persist queue state: {str(e)}")

    def _load_persisted_queue(self):
        """Load persisted queue state from disk with improved error handling"""
        if not self.persistence_path or not os.path.exists(self.persistence_path):
            return

        try:
            with open(self.persistence_path, "r") as f:
                state = json.load(f)

            # Helper function to safely convert items
            def safe_convert_item(item_data):
                try:
                    if isinstance(item_data, dict):
                        # Ensure datetime fields are properly formatted
                        if 'added_at' in item_data and item_data['added_at']:
                            if isinstance(item_data['added_at'], str):
                                try:
                                    item_data['added_at'] = datetime.fromisoformat(item_data['added_at'])
                                except ValueError:
                                    item_data['added_at'] = datetime.utcnow()
                            elif not isinstance(item_data['added_at'], datetime):
                                item_data['added_at'] = datetime.utcnow()

                        if 'last_retry' in item_data and item_data['last_retry']:
                            if isinstance(item_data['last_retry'], str):
                                try:
                                    item_data['last_retry'] = datetime.fromisoformat(item_data['last_retry'])
                                except ValueError:
                                    item_data['last_retry'] = None
                            elif not isinstance(item_data['last_retry'], datetime):
                                item_data['last_retry'] = None

                        if 'last_error_time' in item_data and item_data['last_error_time']:
                            if isinstance(item_data['last_error_time'], str):
                                try:
                                    item_data['last_error_time'] = datetime.fromisoformat(item_data['last_error_time'])
                                except ValueError:
                                    item_data['last_error_time'] = None
                            elif not isinstance(item_data['last_error_time'], datetime):
                                item_data['last_error_time'] = None

                        # Ensure processing_time is a float
                        if 'processing_time' in item_data:
                            try:
                                if isinstance(item_data['processing_time'], str):
                                    item_data['processing_time'] = float(item_data['processing_time'])
                                elif not isinstance(item_data['processing_time'], (int, float)):
                                    item_data['processing_time'] = 0.0
                            except (ValueError, TypeError):
                                item_data['processing_time'] = 0.0

                        return QueueItem(**item_data)
                    return None
                except Exception as e:
                    logger.error(f"Error converting queue item: {e}")
                    return None

            # Restore queue items with proper conversion
            self._queue = []
            for item in state.get("queue", []):
                converted_item = safe_convert_item(item)
                if converted_item:
                    self._queue.append(converted_item)

            # Restore processing items
            self._processing = {}
            for k, v in state.get("processing", {}).items():
                converted_item = safe_convert_item(v)
                if converted_item:
                    self._processing[k] = converted_item

            # Restore completed items
            self._completed = {}
            for k, v in state.get("completed", {}).items():
                converted_item = safe_convert_item(v)
                if converted_item:
                    self._completed[k] = converted_item

            # Restore failed items
            self._failed = {}
            for k, v in state.get("failed", {}).items():
                converted_item = safe_convert_item(v)
                if converted_item:
                    self._failed[k] = converted_item

            # Restore metrics with proper datetime handling
            metrics_data = state.get("metrics", {})
            self.metrics.total_processed = metrics_data.get("total_processed", 0)
            self.metrics.total_failed = metrics_data.get("total_failed", 0)
            self.metrics.avg_processing_time = metrics_data.get("avg_processing_time", 0.0)
            self.metrics.success_rate = metrics_data.get("success_rate", 0.0)
            self.metrics.errors_by_type = metrics_data.get("errors_by_type", {})
            self.metrics.last_error = metrics_data.get("last_error")
            self.metrics.compression_failures = metrics_data.get("compression_failures", 0)
            self.metrics.hardware_accel_failures = metrics_data.get("hardware_accel_failures", 0)

            # Handle metrics datetime fields
            last_error_time = metrics_data.get("last_error_time")
            if last_error_time:
                try:
                    if isinstance(last_error_time, str):
                        self.metrics.last_error_time = datetime.fromisoformat(last_error_time)
                    elif isinstance(last_error_time, datetime):
                        self.metrics.last_error_time = last_error_time
                    else:
                        self.metrics.last_error_time = None
                except ValueError:
                    self.metrics.last_error_time = None

            logger.info("Successfully loaded persisted queue state")

        except Exception as e:
            logger.error(
                f"Error loading persisted queue state: {traceback.format_exc()}"
            )
            # Create backup of corrupted state file
            if os.path.exists(self.persistence_path):
                backup_path = f"{self.persistence_path}.bak.{int(time.time())}"
                try:
                    os.rename(self.persistence_path, backup_path)
                    logger.info(
                        f"Created backup of corrupted state file: {backup_path}"
                    )
                except Exception as be:
                    logger.error(
                        f"Failed to create backup of corrupted state file: {str(be)}"
                    )

    async def _monitor_health(self):
        """Monitor queue health and performance with improved metrics"""
        while not self._shutdown:
            try:
                # Check memory usage
                process = psutil.Process()
                memory_usage = process.memory_info().rss / 1024 / 1024  # MB

                if memory_usage > 1024:  # 1GB
                    logger.warning(f"High memory usage detected: {memory_usage:.2f}MB")
                    # Force garbage collection
                    import gc
                    gc.collect()

                # Check for potential deadlocks
                current_time = time.time()
                processing_times = []
                for item in self._processing.values():
                    if isinstance(item.processing_time, (int, float)) and item.processing_time > 0:
                        processing_times.append(current_time - item.processing_time)

                if processing_times:
                    max_time = max(processing_times)
                    if max_time > self.deadlock_threshold:
                        logger.warning(
                            f"Potential deadlock detected: Item processing for {max_time:.2f}s"
                        )
                        # Attempt recovery
                        await self._recover_stuck_items()

                # Calculate and log detailed metrics
                success_rate = self.metrics.success_rate
                error_distribution = self.metrics.errors_by_type
                avg_processing_time = self.metrics.avg_processing_time

                logger.info(
                    f"Queue Health Metrics:\n"
                    f"- Success Rate: {success_rate:.2%}\n"
                    f"- Avg Processing Time: {avg_processing_time:.2f}s\n"
                    f"- Memory Usage: {memory_usage:.2f}MB\n"
                    f"- Error Distribution: {error_distribution}\n"
                    f"- Queue Size: {len(self._queue)}\n"
                    f"- Processing Items: {len(self._processing)}"
                )

                await asyncio.sleep(300)  # Check every 5 minutes

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitor: {traceback.format_exc()}")
                await asyncio.sleep(60)

    async def _recover_stuck_items(self):
        """Attempt to recover stuck items in the processing queue"""
        try:
            async with self._processing_lock:
                current_time = time.time()
                for url, item in list(self._processing.items()):
                    if (
                        item.processing_time > 0
                        and (current_time - item.processing_time)
                        > self.deadlock_threshold
                    ):
                        # Move to failed queue if max retries reached
                        if item.retry_count >= self.max_retries:
                            self._failed[url] = item
                            self._processing.pop(url)
                            logger.warning(f"Moved stuck item to failed queue: {url}")
                        else:
                            # Increment retry count and reset for reprocessing
                            item.retry_count += 1
                            item.processing_time = 0
                            item.last_retry = datetime.utcnow()
                            item.status = "pending"
                            # Lower priority for stuck items
                            item.priority = max(0, item.priority - 2)
                            self._queue.append(item)
                            self._processing.pop(url)
                            logger.info(f"Recovered stuck item for retry: {url}")

        except Exception as e:
            logger.error(f"Error recovering stuck items: {str(e)}")

    async def _periodic_cleanup(self):
        """Periodically clean up old completed/failed items"""
        while not self._shutdown:
            try:
                current_time = datetime.utcnow()
                cleanup_cutoff = current_time - timedelta(seconds=self.max_history_age)

                async with self._queue_lock:
                    # Clean up completed items
                    for url in list(self._completed.keys()):
                        try:
                            item = self._completed[url]
                            # Ensure added_at is a datetime object
                            if not isinstance(item.added_at, datetime):
                                try:
                                    if isinstance(item.added_at, str):
                                        item.added_at = datetime.fromisoformat(item.added_at)
                                    else:
                                        # If not string or datetime, set to current time
                                        item.added_at = current_time
                                except (ValueError, TypeError):
                                    # If conversion fails, use current time
                                    item.added_at = current_time
                            
                            # Now safe to compare datetimes
                            if item.added_at < cleanup_cutoff:
                                self._completed.pop(url)
                        except Exception as e:
                            logger.error(f"Error processing completed item {url}: {e}")
                            # Remove problematic item
                            self._completed.pop(url)

                    # Clean up failed items
                    for url in list(self._failed.keys()):
                        try:
                            item = self._failed[url]
                            # Ensure added_at is a datetime object
                            if not isinstance(item.added_at, datetime):
                                try:
                                    if isinstance(item.added_at, str):
                                        item.added_at = datetime.fromisoformat(item.added_at)
                                    else:
                                        # If not string or datetime, set to current time
                                        item.added_at = current_time
                                except (ValueError, TypeError):
                                    # If conversion fails, use current time
                                    item.added_at = current_time
                            
                            # Now safe to compare datetimes
                            if item.added_at < cleanup_cutoff:
                                self._failed.pop(url)
                        except Exception as e:
                            logger.error(f"Error processing failed item {url}: {e}")
                            # Remove problematic item
                            self._failed.pop(url)

                    # Clean up guild and channel tracking
                    for guild_id in list(self._guild_queues.keys()):
                        self._guild_queues[guild_id] = {
                            url
                            for url in self._guild_queues[guild_id]
                            if url in self._queue or url in self._processing
                        }

                    for channel_id in list(self._channel_queues.keys()):
                        self._channel_queues[channel_id] = {
                            url
                            for url in self._channel_queues[channel_id]
                            if url in self._queue or url in self._processing
                        }

                self.metrics.last_cleanup = current_time
                logger.info("Completed periodic queue cleanup")

                await asyncio.sleep(self.cleanup_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {traceback.format_exc()}")
                await asyncio.sleep(60)

    def get_queue_status(self, guild_id: int) -> dict:
        """Get current queue status and metrics for a guild"""
        try:
            # Count items for this guild
            pending = len([item for item in self._queue if item.guild_id == guild_id])
            processing = len(
                [
                    item
                    for item in self._processing.values()
                    if item.guild_id == guild_id
                ]
            )
            completed = len(
                [item for item in self._completed.values() if item.guild_id == guild_id]
            )
            failed = len(
                [item for item in self._failed.values() if item.guild_id == guild_id]
            )

            # Get metrics
            metrics = {
                "total_processed": self.metrics.total_processed,
                "total_failed": self.metrics.total_failed,
                "success_rate": self.metrics.success_rate,
                "avg_processing_time": self.metrics.avg_processing_time,
                "peak_memory_usage": self.metrics.peak_memory_usage,
                "last_cleanup": self.metrics.last_cleanup.strftime("%Y-%m-%d %H:%M:%S"),
                "errors_by_type": self.metrics.errors_by_type,
                "compression_failures": self.metrics.compression_failures,
                "hardware_accel_failures": self.metrics.hardware_accel_failures,
            }

            return {
                "pending": pending,
                "processing": processing,
                "completed": completed,
                "failed": failed,
                "metrics": metrics,
            }

        except Exception as e:
            logger.error(f"Error getting queue status: {str(e)}")
            # Return empty status on error
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
        """Clear all queue items for a specific guild"""
        if self._shutdown:
            raise QueueError("Queue manager is shutting down")

        try:
            cleared_count = 0
            async with self._queue_lock:
                # Get URLs for this guild
                guild_urls = self._guild_queues.get(guild_id, set())

                # Clear from pending queue
                self._queue = [
                    item for item in self._queue if item.guild_id != guild_id
                ]

                # Clear from processing
                for url in list(self._processing.keys()):
                    if self._processing[url].guild_id == guild_id:
                        self._processing.pop(url)
                        cleared_count += 1

                # Clear from completed
                for url in list(self._completed.keys()):
                    if self._completed[url].guild_id == guild_id:
                        self._completed.pop(url)
                        cleared_count += 1

                # Clear from failed
                for url in list(self._failed.keys()):
                    if self._failed[url].guild_id == guild_id:
                        self._failed.pop(url)
                        cleared_count += 1

                # Clear guild tracking
                if guild_id in self._guild_queues:
                    cleared_count += len(self._guild_queues[guild_id])
                    self._guild_queues[guild_id].clear()

                # Clear channel tracking for this guild's channels
                for channel_id in list(self._channel_queues.keys()):
                    self._channel_queues[channel_id] = {
                        url
                        for url in self._channel_queues[channel_id]
                        if url not in guild_urls
                    }

            # Persist updated state
            if self.persistence_path:
                await self._persist_queue()

            logger.info(f"Cleared {cleared_count} items from guild {guild_id} queue")
            return cleared_count

        except Exception as e:
            logger.error(f"Error clearing guild queue: {traceback.format_exc()}")
            raise QueueError(f"Failed to clear guild queue: {str(e)}")

