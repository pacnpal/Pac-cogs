"""Queue monitoring and health checks"""

import asyncio
import logging
import psutil
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from .models import QueueItem, QueueMetrics

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("QueueMonitoring")

class QueueMonitor:
    """Monitors queue health and performance"""

    def __init__(
        self,
        deadlock_threshold: int = 60,   # Reduced to 1 minute
        memory_threshold: int = 512,    # 512MB
        max_retries: int = 3,
        check_interval: int = 15        # Reduced to 15 seconds
    ):
        self.deadlock_threshold = deadlock_threshold
        self.memory_threshold = memory_threshold
        self.max_retries = max_retries
        self.check_interval = check_interval
        self._shutdown = False
        self._last_active_time = time.time()
        self._monitoring_task = None

    async def start_monitoring(
        self,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        metrics: QueueMetrics,
        queue_lock: asyncio.Lock
    ) -> None:
        """Start monitoring queue health
        
        Args:
            queue: Reference to the queue list
            processing: Reference to processing dict
            metrics: Reference to queue metrics
            queue_lock: Lock for queue operations
        """
        if self._monitoring_task is not None:
            logger.warning("Monitoring task already running")
            return

        logger.info("Starting queue monitoring...")
        self._monitoring_task = asyncio.create_task(
            self._monitor_loop(queue, processing, metrics, queue_lock)
        )

    async def _monitor_loop(
        self,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        metrics: QueueMetrics,
        queue_lock: asyncio.Lock
    ) -> None:
        """Main monitoring loop"""
        while not self._shutdown:
            try:
                await self._check_health(queue, processing, metrics, queue_lock)
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                logger.info("Queue monitoring cancelled")
                break
            except Exception as e:
                logger.error(f"Error in health monitor: {str(e)}")
                await asyncio.sleep(1)  # Reduced sleep on error

    def stop_monitoring(self) -> None:
        """Stop the monitoring process"""
        logger.info("Stopping queue monitoring...")
        self._shutdown = True
        if self._monitoring_task and not self._monitoring_task.done():
            self._monitoring_task.cancel()
        self._monitoring_task = None

    def update_activity(self) -> None:
        """Update the last active time"""
        self._last_active_time = time.time()

    async def _check_health(
        self,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        metrics: QueueMetrics,
        queue_lock: asyncio.Lock
    ) -> None:
        """Check queue health and performance
        
        Args:
            queue: Reference to the queue list
            processing: Reference to processing dict
            metrics: Reference to queue metrics
            queue_lock: Lock for queue operations
        """
        try:
            current_time = time.time()

            # Check memory usage
            process = psutil.Process()
            memory_usage = process.memory_info().rss / 1024 / 1024  # MB

            if memory_usage > self.memory_threshold:
                logger.warning(f"High memory usage detected: {memory_usage:.2f}MB")
                # Force garbage collection
                import gc
                gc.collect()
                memory_after = process.memory_info().rss / 1024 / 1024
                logger.info(f"Memory after GC: {memory_after:.2f}MB")

            # Check for potential deadlocks
            stuck_items = []

            async with queue_lock:
                # Check processing items
                for url, item in processing.items():
                    if hasattr(item, 'start_time') and item.start_time:
                        processing_time = current_time - item.start_time
                        if processing_time > self.deadlock_threshold:
                            stuck_items.append((url, item))
                            logger.warning(f"Item stuck in processing: {url} for {processing_time:.1f}s")

                # Handle stuck items if found
                if stuck_items:
                    logger.warning(f"Potential deadlock detected: {len(stuck_items)} items stuck")
                    await self._recover_stuck_items(stuck_items, queue, processing)

                # Check overall queue activity
                if processing and current_time - self._last_active_time > self.deadlock_threshold:
                    logger.warning("Queue appears to be hung - no activity detected")
                    # Force recovery of all processing items
                    all_items = list(processing.items())
                    await self._recover_stuck_items(all_items, queue, processing)
                    self._last_active_time = current_time

                # Update metrics
                metrics.last_activity_time = self._last_active_time
                metrics.peak_memory_usage = max(metrics.peak_memory_usage, memory_usage)

                # Calculate current metrics
                queue_size = len(queue)
                processing_count = len(processing)

            # Log detailed metrics
            logger.info(
                f"Queue Health Metrics:\n"
                f"- Success Rate: {metrics.success_rate:.2%}\n"
                f"- Avg Processing Time: {metrics.avg_processing_time:.2f}s\n"
                f"- Memory Usage: {memory_usage:.2f}MB\n"
                f"- Peak Memory: {metrics.peak_memory_usage:.2f}MB\n"
                f"- Error Distribution: {metrics.errors_by_type}\n"
                f"- Queue Size: {queue_size}\n"
                f"- Processing Items: {processing_count}\n"
                f"- Last Activity: {(current_time - self._last_active_time):.1f}s ago"
            )

        except Exception as e:
            logger.error(f"Error checking queue health: {str(e)}")
            # Don't re-raise to keep monitoring alive

    async def _recover_stuck_items(
        self,
        stuck_items: List[tuple[str, QueueItem]],
        queue: List[QueueItem],
        processing: Dict[str, QueueItem]
    ) -> None:
        """Attempt to recover stuck items
        
        Args:
            stuck_items: List of (url, item) tuples for stuck items
            queue: Reference to the queue list
            processing: Reference to processing dict
        """
        try:
            recovered = 0
            failed = 0
            
            for url, item in stuck_items:
                try:
                    # Move to failed if max retries reached
                    if item.retry_count >= self.max_retries:
                        logger.warning(f"Moving stuck item to failed: {url}")
                        item.status = "failed"
                        item.error = "Exceeded maximum retries after being stuck"
                        item.last_error = item.error
                        item.last_error_time = datetime.utcnow()
                        processing.pop(url)
                        failed += 1
                    else:
                        # Reset for retry
                        logger.info(f"Recovering stuck item for retry: {url}")
                        item.retry_count += 1
                        item.start_time = None
                        item.processing_time = 0
                        item.last_retry = datetime.utcnow()
                        item.status = "pending"
                        item.priority = max(0, item.priority - 2)  # Lower priority
                        queue.append(item)
                        processing.pop(url)
                        recovered += 1
                except Exception as e:
                    logger.error(f"Error recovering item {url}: {str(e)}")

            # Update activity timestamp after recovery
            self.update_activity()
            logger.info(f"Recovery complete - Recovered: {recovered}, Failed: {failed}")

        except Exception as e:
            logger.error(f"Error recovering stuck items: {str(e)}")
            # Don't re-raise to keep monitoring alive

class MonitoringError(Exception):
    """Base exception for monitoring-related errors"""
    pass
