"""Queue processing functionality for video processing"""

import logging
import asyncio
from typing import List, Optional, Dict, Any, Set, ClassVar
from datetime import datetime

#try:
    # Try relative imports first
from ..queue.types import QueuePriority, QueueMetrics, ProcessingMetrics
from ..queue.models import QueueItem
#except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.queue.types import QueuePriority, QueueMetrics, ProcessingMetrics
    # from videoarchiver.queue.models import QueueItem

logger = logging.getLogger("VideoArchiver")

class QueueProcessor:
    """Handles processing of video queue items"""

    _active_items: ClassVar[Set[int]] = set()
    _processing_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(self, queue_manager):
        """Initialize queue processor
        
        Args:
            queue_manager: Queue manager instance to handle queue operations
        """
        self.queue_manager = queue_manager
        self._metrics = ProcessingMetrics()

    async def process_urls(self, message, urls, priority: QueuePriority = QueuePriority.NORMAL) -> None:
        """Process URLs from a message
        
        Args:
            message: Discord message containing URLs
            urls: List of URLs to process
            priority: Processing priority level
        """
        for url_metadata in urls:
            await self.queue_manager.add_to_queue(
                url=url_metadata.url,
                message_id=message.id,
                channel_id=message.channel.id,
                guild_id=message.guild.id,
                author_id=message.author.id,
                priority=priority.value
            )

    async def process_item(self, item: QueueItem) -> bool:
        """Process a single queue item

        Args:
            item: Queue item to process

        Returns:
            bool: Success status
        """
        if item.id in self._active_items:
            logger.warning(f"Item {item.id} is already being processed")
            return False

        try:
            self._active_items.add(item.id)
            start_time = datetime.now()

            # Process item logic here
            # Placeholder for actual video processing
            await asyncio.sleep(1)

            processing_time = (datetime.now() - start_time).total_seconds()
            self._update_metrics(processing_time, True, item.size)
            return True

        except Exception as e:
            logger.error(f"Error processing item {item.id}: {str(e)}")
            self._update_metrics(0, False, 0)
            return False

        finally:
            self._active_items.remove(item.id)

    def _update_metrics(self, processing_time: float, success: bool, size: int) -> None:
        """Update processing metrics"""
        if success:
            self._metrics.record_success(processing_time)
        else:
            self._metrics.record_failure("Processing error")

    def get_metrics(self) -> QueueMetrics:
        """Get current processing metrics"""
        total = self._metrics.total_processed
        if total == 0:
            return QueueMetrics(
                total_items=0,
                processing_time=0,
                success_rate=0,
                error_rate=0,
                average_size=0,
            )

        return QueueMetrics(
            total_items=total,
            processing_time=self._metrics.avg_processing_time,
            success_rate=self._metrics.successful / total,
            error_rate=self._metrics.failed / total,
            average_size=0,  # This would need to be tracked separately if needed
        )
