"""Queue processing functionality for video processing"""

import logging
import asyncio
from enum import Enum, auto
from typing import List, Optional, Dict, Any, Set, Union, TypedDict, ClassVar
from datetime import datetime
import discord

from videoarchiver.queue.models import QueueItem
from videoarchiver.queue.manager import EnhancedVideoQueueManager
from videoarchiver.processor.constants import REACTIONS
from videoarchiver.processor.url_extractor import URLMetadata
from videoarchiver.utils.exceptions import QueueProcessingError

logger = logging.getLogger("VideoArchiver")

class QueuePriority(Enum):
    """Priority levels for queue processing"""
    HIGH = auto()
    NORMAL = auto()
    LOW = auto()

class QueueMetrics(TypedDict):
    """Type definition for queue metrics"""
    total_items: int
    processing_time: float
    success_rate: float
    error_rate: float
    average_size: float

class QueueProcessor:
    """Handles processing of video queue items"""
    
    _active_items: ClassVar[Set[int]] = set()
    _processing_lock: ClassVar[asyncio.Lock] = asyncio.Lock()
    
    def __init__(self, queue_manager: EnhancedVideoQueueManager):
        self.queue_manager = queue_manager
        self._metrics: Dict[str, Any] = {
            'processed_count': 0,
            'error_count': 0,
            'total_size': 0,
            'total_time': 0
        }
    
    async def process_item(self, item: QueueItem) -> bool:
        """
        Process a single queue item
        
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
        self._metrics['processed_count'] += 1
        self._metrics['total_time'] += processing_time
        
        if not success:
            self._metrics['error_count'] += 1
            
        if size > 0:
            self._metrics['total_size'] += size
    
    def get_metrics(self) -> QueueMetrics:
        """Get current processing metrics"""
        total = self._metrics['processed_count']
        if total == 0:
            return QueueMetrics(
                total_items=0,
                processing_time=0,
                success_rate=0,
                error_rate=0,
                average_size=0
            )
            
        return QueueMetrics(
            total_items=total,
            processing_time=self._metrics['total_time'],
            success_rate=(total - self._metrics['error_count']) / total,
            error_rate=self._metrics['error_count'] / total,
            average_size=self._metrics['total_size'] / total
        )
