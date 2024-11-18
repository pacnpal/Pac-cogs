"""Module for processing queue items"""

import asyncio
import logging
import time
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Optional, Tuple, List, Set, Dict, Any
from datetime import datetime, timedelta

from models import QueueItem
from state_manager import QueueStateManager, ItemState
from monitoring import QueueMonitor

logger = logging.getLogger("QueueProcessor")

class ProcessingStrategy(Enum):
    """Processing strategies"""
    SEQUENTIAL = "sequential"  # Process items one at a time
    CONCURRENT = "concurrent"  # Process multiple items concurrently
    BATCHED = "batched"      # Process items in batches
    PRIORITY = "priority"    # Process based on priority

@dataclass
class ProcessingMetrics:
    """Metrics for processing operations"""
    total_processed: int = 0
    successful: int = 0
    failed: int = 0
    retried: int = 0
    avg_processing_time: float = 0.0
    peak_concurrent_tasks: int = 0
    last_processed: Optional[datetime] = None
    error_counts: Dict[str, int] = None

    def __post_init__(self):
        self.error_counts = {}

    def record_success(self, processing_time: float) -> None:
        """Record successful processing"""
        self.total_processed += 1
        self.successful += 1
        self._update_avg_time(processing_time)
        self.last_processed = datetime.utcnow()

    def record_failure(self, error: str) -> None:
        """Record processing failure"""
        self.total_processed += 1
        self.failed += 1
        self.error_counts[error] = self.error_counts.get(error, 0) + 1
        self.last_processed = datetime.utcnow()

    def record_retry(self) -> None:
        """Record processing retry"""
        self.retried += 1

    def _update_avg_time(self, new_time: float) -> None:
        """Update average processing time"""
        if self.total_processed == 1:
            self.avg_processing_time = new_time
        else:
            self.avg_processing_time = (
                (self.avg_processing_time * (self.total_processed - 1) + new_time)
                / self.total_processed
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return {
            "total_processed": self.total_processed,
            "successful": self.successful,
            "failed": self.failed,
            "retried": self.retried,
            "success_rate": (
                self.successful / self.total_processed
                if self.total_processed > 0
                else 0
            ),
            "avg_processing_time": self.avg_processing_time,
            "peak_concurrent_tasks": self.peak_concurrent_tasks,
            "last_processed": (
                self.last_processed.isoformat()
                if self.last_processed
                else None
            ),
            "error_distribution": self.error_counts
        }

class BatchManager:
    """Manages processing batches"""

    def __init__(
        self,
        batch_size: int,
        max_concurrent: int,
        timeout: float = 30.0
    ):
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.current_batch: List[QueueItem] = []
        self.processing_start: Optional[datetime] = None

    async def process_batch(
        self,
        items: List[QueueItem],
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]]
    ) -> List[Tuple[QueueItem, bool, Optional[str]]]:
        """Process a batch of items"""
        self.current_batch = items
        self.processing_start = datetime.utcnow()

        tasks = [
            asyncio.create_task(self._process_item(processor, item))
            for item in items
        ]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return [
                (item, *self._handle_result(result))
                for item, result in zip(items, results)
            ]
        finally:
            self.current_batch = []
            self.processing_start = None

    async def _process_item(
        self,
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]],
        item: QueueItem
    ) -> Tuple[bool, Optional[str]]:
        """Process a single item with timeout"""
        try:
            return await asyncio.wait_for(
                processor(item),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            return False, "Processing timeout"
        except Exception as e:
            return False, str(e)

    def _handle_result(
        self,
        result: Any
    ) -> Tuple[bool, Optional[str]]:
        """Handle processing result"""
        if isinstance(result, tuple) and len(result) == 2:
            return result
        if isinstance(result, Exception):
            return False, str(result)
        return False, "Unknown error"

    def get_batch_status(self) -> Dict[str, Any]:
        """Get current batch status"""
        return {
            "batch_size": len(self.current_batch),
            "processing_time": (
                (datetime.utcnow() - self.processing_start).total_seconds()
                if self.processing_start
                else 0
            ),
            "items": [item.url for item in self.current_batch]
        }

class QueueProcessor:
    """Handles the processing of queue items"""

    def __init__(
        self,
        state_manager: QueueStateManager,
        monitor: QueueMonitor,
        strategy: ProcessingStrategy = ProcessingStrategy.CONCURRENT,
        max_retries: int = 3,
        retry_delay: int = 5,
        batch_size: int = 5,
        max_concurrent: int = 3
    ):
        self.state_manager = state_manager
        self.monitor = monitor
        self.strategy = strategy
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        self.batch_manager = BatchManager(batch_size, max_concurrent)
        self.metrics = ProcessingMetrics()
        
        self._shutdown = False
        self._active_tasks: Set[asyncio.Task] = set()
        self._processing_lock = asyncio.Lock()

    async def start_processing(
        self,
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]]
    ) -> None:
        """Start processing items in the queue"""
        logger.info(f"Queue processor started with strategy: {self.strategy.value}")
        
        while not self._shutdown:
            try:
                if self.strategy == ProcessingStrategy.BATCHED:
                    await self._process_batch(processor)
                elif self.strategy == ProcessingStrategy.CONCURRENT:
                    await self._process_concurrent(processor)
                else:  # SEQUENTIAL or PRIORITY
                    await self._process_sequential(processor)

            except asyncio.CancelledError:
                logger.info("Queue processing cancelled")
                break
            except Exception as e:
                logger.error(f"Critical error in queue processor: {e}")
                await asyncio.sleep(1)  # Delay before retry

            await asyncio.sleep(0)

    async def _process_batch(
        self,
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]]
    ) -> None:
        """Process items in batches"""
        items = await self.state_manager.get_next_items(self.batch_manager.batch_size)
        if not items:
            await asyncio.sleep(0.1)
            return

        start_time = time.time()
        results = await self.batch_manager.process_batch(items, processor)
        
        for item, success, error in results:
            await self._handle_result(
                item,
                success,
                error,
                time.time() - start_time
            )

    async def _process_concurrent(
        self,
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]]
    ) -> None:
        """Process items concurrently"""
        if len(self._active_tasks) >= self.batch_manager.max_concurrent:
            await asyncio.sleep(0.1)
            return

        items = await self.state_manager.get_next_items(
            self.batch_manager.max_concurrent - len(self._active_tasks)
        )
        
        for item in items:
            task = asyncio.create_task(self._process_item(processor, item))
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)

        self.metrics.peak_concurrent_tasks = max(
            self.metrics.peak_concurrent_tasks,
            len(self._active_tasks)
        )

    async def _process_sequential(
        self,
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]]
    ) -> None:
        """Process items sequentially"""
        items = await self.state_manager.get_next_items(1)
        if not items:
            await asyncio.sleep(0.1)
            return

        await self._process_item(processor, items[0])

    async def _process_item(
        self,
        processor: Callable[[QueueItem], Tuple[bool, Optional[str]]],
        item: QueueItem
    ) -> None:
        """Process a single queue item"""
        try:
            logger.info(f"Processing queue item: {item.url}")
            start_time = time.time()
            
            async with self._processing_lock:
                item.start_processing()
                self.monitor.update_activity()
                
                success, error = await processor(item)
                
                processing_time = time.time() - start_time
                await self._handle_result(item, success, error, processing_time)

        except Exception as e:
            logger.error(f"Error processing {item.url}: {e}")
            await self._handle_result(item, False, str(e), 0)

    async def _handle_result(
        self,
        item: QueueItem,
        success: bool,
        error: Optional[str],
        processing_time: float
    ) -> None:
        """Handle processing result"""
        item.finish_processing(success, error)
        
        if success:
            await self.state_manager.mark_completed(item, True)
            self.metrics.record_success(processing_time)
            logger.info(f"Successfully processed: {item.url}")
        else:
            if item.retry_count < self.max_retries:
                item.retry_count += 1
                await self.state_manager.retry_item(item)
                self.metrics.record_retry()
                logger.warning(f"Retrying: {item.url} (attempt {item.retry_count})")
                await asyncio.sleep(self.retry_delay)
            else:
                await self.state_manager.mark_completed(item, False, error)
                self.metrics.record_failure(error or "Unknown error")
                logger.error(f"Failed after {self.max_retries} attempts: {item.url}")

    async def stop_processing(self) -> None:
        """Stop processing queue items"""
        self._shutdown = True
        
        # Cancel all active tasks
        for task in self._active_tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to complete
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        
        self._active_tasks.clear()
        logger.info("Queue processor stopped")

    def is_processing(self) -> bool:
        """Check if the processor is currently processing items"""
        return bool(self._active_tasks)

    def get_processor_stats(self) -> Dict[str, Any]:
        """Get processor statistics"""
        return {
            "strategy": self.strategy.value,
            "active_tasks": len(self._active_tasks),
            "metrics": self.metrics.get_stats(),
            "batch_status": self.batch_manager.get_batch_status(),
            "is_processing": self.is_processing()
        }
