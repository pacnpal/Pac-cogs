import logging
import asyncio
from typing import List, Optional, Dict, Any, Set, ClassVar
from datetime import datetime
import sys
from pathlib import Path

# Get the parent directory (videoarchiver root)
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Use non-relative imports
from queue.q_types import QueuePriority, QueueMetrics, ProcessingMetrics
from queue.models import QueueItem

logger = logging.getLogger("VideoArchiver")


class QueueProcessor:
    """
    Handles the processing of queue items with priority-based scheduling.
    """

    # Class variables for tracking global state
    active_items: ClassVar[Set[str]] = set()
    processing_metrics: ClassVar[Dict[str, ProcessingMetrics]] = {}

    def __init__(self):
        self.queue_metrics = QueueMetrics()
        self.processing_lock = asyncio.Lock()
        self.is_running = False
        self._current_item: Optional[QueueItem] = None
        self._priority_queues: Dict[QueuePriority, List[QueueItem]] = {
            priority: [] for priority in QueuePriority
        }

    @property
    def current_item(self) -> Optional[QueueItem]:
        """Get the currently processing item."""
        return self._current_item

    def add_item(self, item: QueueItem) -> bool:
        """
        Add an item to the appropriate priority queue.

        Args:
            item: QueueItem to add

        Returns:
            bool: True if item was added successfully
        """
        if item.id in self.active_items:
            logger.warning(f"Item {item.id} is already in queue")
            return False

        self._priority_queues[item.priority].append(item)
        self.active_items.add(item.id)
        self.queue_metrics.total_items += 1
        logger.info(f"Added item {item.id} to {item.priority.name} priority queue")
        return True

    def remove_item(self, item_id: str) -> Optional[QueueItem]:
        """
        Remove an item from any priority queue.

        Args:
            item_id: ID of item to remove

        Returns:
            Optional[QueueItem]: Removed item if found, None otherwise
        """
        for priority in QueuePriority:
            queue = self._priority_queues[priority]
            for item in queue:
                if item.id == item_id:
                    queue.remove(item)
                    self.active_items.discard(item_id)
                    self.queue_metrics.total_items -= 1
                    logger.info(
                        f"Removed item {item_id} from {priority.name} priority queue"
                    )
                    return item
        return None

    def _update_metrics(self, processing_time: float, success: bool, size: int) -> None:
        """
        Update processing metrics.

        Args:
            processing_time: Time taken to process the item
            success: Whether processing was successful
            size: Size of the processed item
        """
        if success:
            self.queue_metrics.record_success(processing_time)
        else:
            self.queue_metrics.record_failure("Processing error")

    def get_metrics(self) -> QueueMetrics:
        """
        Get current processing metrics.

        Returns:
            QueueMetrics: Current queue processing metrics
        """
        total = self.queue_metrics.total_processed
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
            processing_time=self.queue_metrics.avg_processing_time,
            success_rate=self.queue_metrics.successful / total,
            error_rate=self.queue_metrics.failed / total,
            average_size=0,  # This would need to be tracked separately if needed
        )
