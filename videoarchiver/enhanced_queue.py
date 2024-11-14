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
import weakref
from pathlib import Path
import aiofiles
import aiofiles.os
import sys
import signal
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import tempfile
import shutil
from .exceptions import (
    QueueError,
    ResourceExhaustedError,
    ProcessingError,
    CleanupError,
    FileOperationError
)

# Configure logging with proper format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('EnhancedQueueManager')

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
    processing_time: float = 0.0
    size_bytes: int = 0
    last_error: Optional[str] = None
    retry_count: int = 0
    last_retry: Optional[datetime] = None
        self.processing_times: List[float] = []
        self.last_error: Optional[str] = None
        self.last_error_time: Optional[datetime] = None
        
    def update_metrics(self, processing_time: float, success: bool, error: str = None):
        """Update metrics with new processing information"""
        self.total_processed += 1
        if not success:
            self.total_failed += 1
            if error:
                self.last_error = error
                self.last_error_time = datetime.utcnow()
                error_type = error.split(':')[0] if ':' in error else error
                self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1
        
        # Update processing times with sliding window
        self.processing_times.append(processing_time)
        if len(self.processing_times) > 100:  # Keep last 100 processing times
            self.processing_times.pop(0)
        
        # Update average processing time
        self.avg_processing_time = sum(self.processing_times) / len(self.processing_times)
        
        # Update success rate
        self.success_rate = (
            (self.total_processed - self.total_failed) / self.total_processed
            if self.total_processed > 0 else 0.0
        )
        
        # Update peak memory usage
        current_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        self.peak_memory_usage = max(self.peak_memory_usage, current_memory)

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
        backup_interval: int = 300  # 5 minutes
    ):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_queue_size = max_queue_size
        self.cleanup_interval = cleanup_interval
        self.max_history_age = max_history_age
        self.persistence_path = persistence_path
        self.backup_interval = backup_interval
        
        # Queue storage with priority
        self._queue: List[QueueItem] = []
        self._queue_lock = asyncio.Lock()
        self._processing: Dict[str, QueueItem] = {}
        self._completed: Dict[str, QueueItem] = {}
        self._failed: Dict[str, QueueItem] = {}
        
        # Track active tasks
        self._active_tasks: Set[asyncio.Task] = set()
        self._processing_lock = asyncio.Lock()
        
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

    async def add_to_queue(
        self,
        url: str,
        message_id: int,
        channel_id: int,
        guild_id: int,
        author_id: int,
        callback: Callable[[str, bool, str], Any],
        priority: int = 0
    ) -> bool:
        """Add a video to the processing queue with priority support"""
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
                    priority=priority
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
        while True:
            try:
                if self.persistence_path and (
                    not self._last_backup
                    or (datetime.utcnow() - self._last_backup).total_seconds() >= self.backup_interval
                ):
                    await self._persist_queue()
                    self._last_backup = datetime.utcnow()
                await asyncio.sleep(self.backup_interval)
            except Exception as e:
                logger.error(f"Error in periodic backup: {str(e)}")
                await asyncio.sleep(60)

    async def _persist_queue(self):
        """Persist queue state to disk with improved error handling"""
        if not self.persistence_path:
            return
            
        try:
            state = {
                "queue": [asdict(item) for item in self._queue],
                "processing": {k: asdict(v) for k, v in self._processing.items()},
                "completed": {k: asdict(v) for k, v in self._completed.items()},
                "failed": {k: asdict(v) for k, v in self._failed.items()},
                "metrics": {
                    "total_processed": self.metrics.total_processed,
                    "total_failed": self.metrics.total_failed,
                    "avg_processing_time": self.metrics.avg_processing_time,
                    "success_rate": self.metrics.success_rate,
                    "errors_by_type": self.metrics.errors_by_type,
                    "last_error": self.metrics.last_error,
                    "last_error_time": self.metrics.last_error_time.isoformat() if self.metrics.last_error_time else None
                }
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.persistence_path), exist_ok=True)
            
            # Write to temp file first
            temp_path = f"{self.persistence_path}.tmp"
            async with aiofiles.open(temp_path, 'w') as f:
                await f.write(json.dumps(state, default=str))
                await f.flush()
                os.fsync(f.fileno())
                
            # Atomic rename
            await aiofiles.os.rename(temp_path, self.persistence_path)
            
        except Exception as e:
            logger.error(f"Error persisting queue state: {traceback.format_exc()}")
            raise QueueError(f"Failed to persist queue state: {str(e)}")

    def _load_persisted_queue(self):
        """Load persisted queue state from disk with improved error handling"""
        if not self.persistence_path or not os.path.exists(self.persistence_path):
            return
            
        try:
            with open(self.persistence_path, 'r') as f:
                state = json.load(f)
                
            # Restore queue items with datetime conversion
            self._queue = []
            for item in state["queue"]:
                item["added_at"] = datetime.fromisoformat(item["added_at"])
                if item.get("last_retry"):
                    item["last_retry"] = datetime.fromisoformat(item["last_retry"])
                self._queue.append(QueueItem(**item))
                
            self._processing = {k: QueueItem(**v) for k, v in state["processing"].items()}
            self._completed = {k: QueueItem(**v) for k, v in state["completed"].items()}
            self._failed = {k: QueueItem(**v) for k, v in state["failed"].items()}
            
            # Restore metrics
            self.metrics.total_processed = state["metrics"]["total_processed"]
            self.metrics.total_failed = state["metrics"]["total_failed"]
            self.metrics.avg_processing_time = state["metrics"]["avg_processing_time"]
            self.metrics.success_rate = state["metrics"]["success_rate"]
            self.metrics.errors_by_type = state["metrics"]["errors_by_type"]
            self.metrics.last_error = state["metrics"]["last_error"]
            if state["metrics"]["last_error_time"]:
                self.metrics.last_error_time = datetime.fromisoformat(state["metrics"]["last_error_time"])
            
            logger.info("Successfully loaded persisted queue state")
            
        except Exception as e:
            logger.error(f"Error loading persisted queue state: {traceback.format_exc()}")
            # Create backup of corrupted state file
            if os.path.exists(self.persistence_path):
                backup_path = f"{self.persistence_path}.bak.{int(time.time())}"
                try:
                    os.rename(self.persistence_path, backup_path)
                    logger.info(f"Created backup of corrupted state file: {backup_path}")
                except Exception as be:
                    logger.error(f"Failed to create backup of corrupted state file: {str(be)}")

    async def _monitor_health(self):
        """Monitor queue health and performance with improved metrics"""
        while True:
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
                processing_times = [
                    time.time() - item.processing_time
                    for item in self._processing.values()
                    if item.processing_time > 0
                ]
                
                if processing_times:
                    max_time = max(processing_times)
                    if max_time > 3600:  # 1 hour
                        logger.warning(f"Potential deadlock detected: Item processing for {max_time:.2f}s")
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
                
            except Exception as e:
                logger.error(f"Error in health monitor: {traceback.format_exc()}")
                await asyncio.sleep(60)

    async def _recover_stuck_items(self):
        """Attempt to recover stuck items in the processing queue"""
        try:
            async with self._processing_lock:
                current_time = time.time()
                for url, item in list(self._processing.items()):
                    if item.processing_time > 0 and (current_time - item.processing_time) > 3600:
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
                            self._queue.append(item)
                            self._processing.pop(url)
                            logger.info(f"Recovered stuck item for retry: {url}")
                            
        except Exception as e:
            logger.error(f"Error recovering stuck items: {str(e)}")

    async def cleanup(self):
        """Clean up resources and stop queue processing"""
        try:
            # Cancel all monitoring tasks
            for task in self._active_tasks:
                if not task.done():
                    task.cancel()
            
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
            
            # Persist final state
            if self.persistence_path:
                await self._persist_queue()
            
            # Clear all collections
            self._queue.clear()
            self._processing.clear()
            self._completed.clear()
            self._failed.clear()
            self._guild_queues.clear()
            self._channel_queues.clear()
            
            logger.info("Queue manager cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            raise CleanupError(f"Failed to clean up queue manager: {str(e)}")

    def get_queue_status(self, guild_id: Optional[int] = None) -> Dict[str, Any]:
        """Get detailed queue status with metrics"""
        try:
            if guild_id is not None:
                guild_urls = self._guild_queues.get(guild_id, set())
                status = {
                    "pending": sum(1 for item in self._queue if item.url in guild_urls),
                    "processing": sum(1 for url in self._processing if url in guild_urls),
                    "completed": sum(1 for url in self._completed if url in guild_urls),
                    "failed": sum(1 for url in self._failed if url in guild_urls)
                }
            else:
                status = {
                    "pending": len(self._queue),
                    "processing": len(self._processing),
                    "completed": len(self._completed),
                    "failed": len(self._failed)
                }
                
            # Add detailed metrics
            status.update({
                "metrics": {
                    "total_processed": self.metrics.total_processed,
                    "total_failed": self.metrics.total_failed,
                    "success_rate": self.metrics.success_rate,
                    "avg_processing_time": self.metrics.avg_processing_time,
                    "peak_memory_usage": self.metrics.peak_memory_usage,
                    "last_cleanup": self.metrics.last_cleanup.isoformat(),
                    "errors_by_type": self.metrics.errors_by_type,
                    "last_error": self.metrics.last_error,
                    "last_error_time": self.metrics.last_error_time.isoformat() if self.metrics.last_error_time else None,
                    "retries": self.metrics.retries
                }
            })
            
            return status
            
        except Exception as e:
            logger.error(f"Error getting queue status: {str(e)}")
            raise QueueError(f"Failed to get queue status: {str(e)}")

    async def _periodic_cleanup(self):
        """Periodically clean up old completed/failed items"""
        while True:
            try:
                current_time = datetime.utcnow()
                cleanup_cutoff = current_time - timedelta(seconds=self.max_history_age)
                
                async with self._queue_lock:
                    # Clean up completed items
                    for url in list(self._completed.keys()):
                        item = self._completed[url]
                        if item.added_at < cleanup_cutoff:
                            self._completed.pop(url)
                            
                    # Clean up failed items
                    for url in list(self._failed.keys()):
                        item = self._failed[url]
                        if item.added_at < cleanup_cutoff:
                            self._failed.pop(url)
                    
                    # Clean up guild and channel tracking
                    for guild_id in list(self._guild_queues.keys()):
                        self._guild_queues[guild_id] = {
                            url for url in self._guild_queues[guild_id]
                            if url in self._queue or url in self._processing
                        }
                        
                    for channel_id in list(self._channel_queues.keys()):
                        self._channel_queues[channel_id] = {
                            url for url in self._channel_queues[channel_id]
                            if url in self._queue or url in self._processing
                        }
                
                self.metrics.last_cleanup = current_time
                logger.info("Completed periodic queue cleanup")
                
                await asyncio.sleep(self.cleanup_interval)
                
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {traceback.format_exc()}")
                await asyncio.sleep(60)