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
        deadlock_threshold: int = 900,  # 15 minutes
        memory_threshold: int = 1024,  # 1GB
        max_retries: int = 3
    ):
        self.deadlock_threshold = deadlock_threshold
        self.memory_threshold = memory_threshold
        self.max_retries = max_retries
        self._shutdown = False

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
        while not self._shutdown:
            try:
                await self._check_health(queue, processing, metrics, processing_lock)
                await asyncio.sleep(300)  # Check every 5 minutes

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitor: {str(e)}")
                await asyncio.sleep(60)

    def stop_monitoring(self) -> None:
        """Stop the monitoring process"""
        self._shutdown = True

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
            # Check memory usage
            process = psutil.Process()
            memory_usage = process.memory_info().rss / 1024 / 1024  # MB

            if memory_usage > self.memory_threshold:
                logger.warning(f"High memory usage detected: {memory_usage:.2f}MB")
                # Force garbage collection
                import gc
                gc.collect()

            # Check for potential deadlocks
            current_time = time.time()
            processing_times = []
            stuck_items = []

            for url, item in processing.items():
                if isinstance(item.processing_time, (int, float)) and item.processing_time > 0:
                    processing_time = current_time - item.processing_time
                    processing_times.append(processing_time)
                    if processing_time > self.deadlock_threshold:
                        stuck_items.append((url, item))

            if stuck_items:
                logger.warning(
                    f"Potential deadlock detected: {len(stuck_items)} items stuck"
                )
                await self._recover_stuck_items(
                    stuck_items, queue, processing, processing_lock
                )

            # Calculate and log metrics
            success_rate = metrics.success_rate
            error_distribution = metrics.errors_by_type
            avg_processing_time = metrics.avg_processing_time

            # Update peak memory usage
            metrics.peak_memory_usage = max(metrics.peak_memory_usage, memory_usage)

            logger.info(
                f"Queue Health Metrics:\n"
                f"- Success Rate: {success_rate:.2%}\n"
                f"- Avg Processing Time: {avg_processing_time:.2f}s\n"
                f"- Memory Usage: {memory_usage:.2f}MB\n"
                f"- Error Distribution: {error_distribution}\n"
                f"- Queue Size: {len(queue)}\n"
                f"- Processing Items: {len(processing)}"
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
            async with processing_lock:
                for url, item in stuck_items:
                    # Move to failed if max retries reached
                    if item.retry_count >= self.max_retries:
                        logger.warning(f"Moving stuck item to failed: {url}")
                        item.status = "failed"
                        item.error = "Exceeded maximum retries after being stuck"
                        item.last_error = item.error
                        item.last_error_time = datetime.utcnow()
                        processing.pop(url)
                    else:
                        # Reset for retry
                        logger.info(f"Recovering stuck item for retry: {url}")
                        item.retry_count += 1
                        item.processing_time = 0
                        item.last_retry = datetime.utcnow()
                        item.status = "pending"
                        item.priority = max(0, item.priority - 2)  # Lower priority
                        queue.append(item)
                        processing.pop(url)

        except Exception as e:
            logger.error(f"Error recovering stuck items: {str(e)}")
            raise

class MonitoringError(Exception):
    """Base exception for monitoring-related errors"""
    pass
