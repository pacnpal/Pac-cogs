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
        deadlock_threshold: int = 300,  # 5 minutes
        memory_threshold: int = 512,    # 512MB
        max_retries: int = 3,
        check_interval: int = 60        # Check every minute
    ):
        self.deadlock_threshold = deadlock_threshold
        self.memory_threshold = memory_threshold
        self.max_retries = max_retries
        self.check_interval = check_interval
        self._shutdown = False
        self._last_active_time = time.time()

    async def start_monitoring(
        self,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        metrics: QueueMetrics,
        processing_lock: asyncio.Lock
    ) -> None:
        """Start monitoring queue health
        
        Args:
            queue: Reference to the queue list
            processing: Reference to processing dict
            metrics: Reference to queue metrics
            processing_lock: Lock for processing dict
        """
        logger.info("Starting queue monitoring...")
        while not self._shutdown:
            try:
                await self._check_health(queue, processing, metrics, processing_lock)
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                logger.info("Queue monitoring cancelled")
                break
            except Exception as e:
                logger.error(f"Error in health monitor: {str(e)}")
                await asyncio.sleep(30)  # Shorter sleep on error

    def stop_monitoring(self) -> None:
        """Stop the monitoring process"""
        logger.info("Stopping queue monitoring...")
        self._shutdown = True

    def update_activity(self) -> None:
        """Update the last active time"""
        self._last_active_time = time.time()

    async def _check_health(
        self,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        metrics: QueueMetrics,
        processing_lock: asyncio.Lock
    ) -> None:
        """Check queue health and performance
        
        Args:
            queue: Reference to the queue list
            processing: Reference to processing dict
            metrics: Reference to queue metrics
            processing_lock: Lock for processing dict
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
            processing_times = []
            stuck_items = []

            async with processing_lock:
                for url, item in processing.items():
                    # Check if item has started processing
                    if hasattr(item, 'start_time') and item.start_time:
                        processing_time = current_time - item.start_time
                        processing_times.append(processing_time)
                        if processing_time > self.deadlock_threshold:
                            stuck_items.append((url, item))
                            logger.warning(f"Item stuck in processing: {url} for {processing_time:.1f}s")

            if stuck_items:
                logger.warning(
                    f"Potential deadlock detected: {len(stuck_items)} items stuck"
                )
                await self._recover_stuck_items(
                    stuck_items, queue, processing, processing_lock
                )

            # Check overall queue activity
            if processing and current_time - self._last_active_time > self.deadlock_threshold:
                logger.warning("Queue appears to be hung - no activity detected")
                # Force recovery of all processing items
                async with processing_lock:
                    all_items = list(processing.items())
                    await self._recover_stuck_items(
                        all_items, queue, processing, processing_lock
                    )
                self._last_active_time = current_time

            # Calculate and log metrics
            success_rate = metrics.success_rate
            error_distribution = metrics.errors_by_type
            avg_processing_time = metrics.avg_processing_time

            # Update peak memory usage
            metrics.peak_memory_usage = max(metrics.peak_memory_usage, memory_usage)

            # Log detailed metrics
            logger.info(
                f"Queue Health Metrics:\n"
                f"- Success Rate: {success_rate:.2%}\n"
                f"- Avg Processing Time: {avg_processing_time:.2f}s\n"
                f"- Memory Usage: {memory_usage:.2f}MB\n"
                f"- Peak Memory: {metrics.peak_memory_usage:.2f}MB\n"
                f"- Error Distribution: {error_distribution}\n"
                f"- Queue Size: {len(queue)}\n"
                f"- Processing Items: {len(processing)}\n"
                f"- Last Activity: {(current_time - self._last_active_time):.1f}s ago"
            )

        except Exception as e:
            logger.error(f"Error checking queue health: {str(e)}")
            raise

    async def _recover_stuck_items(
        self,
        stuck_items: List[tuple[str, QueueItem]],
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        processing_lock: asyncio.Lock
    ) -> None:
        """Attempt to recover stuck items
        
        Args:
            stuck_items: List of (url, item) tuples for stuck items
            queue: Reference to the queue list
            processing: Reference to processing dict
            processing_lock: Lock for processing dict
        """
        try:
            recovered = 0
            failed = 0
            
            async with processing_lock:
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

            logger.info(f"Recovery complete - Recovered: {recovered}, Failed: {failed}")

        except Exception as e:
            logger.error(f"Error recovering stuck items: {str(e)}")
            raise

class MonitoringError(Exception):
    """Base exception for monitoring-related errors"""
    pass
