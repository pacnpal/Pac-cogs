"""Queue processing functionality for video processing"""

import logging
import asyncio
from enum import Enum, auto
from typing import List, Optional, Dict, Any, Set, Union, TypedDict, ClassVar
from datetime import datetime
import discord

from ..queue.models import QueueItem
from ..queue.manager import EnhancedVideoQueueManager
from .constants import REACTIONS
from .url_extractor import URLMetadata
from ..utils.exceptions import QueueProcessingError

logger = logging.getLogger("VideoArchiver")

class QueuePriority(Enum):
    """Queue item priorities"""
    HIGH = auto()
    NORMAL = auto()
    LOW = auto()

class ProcessingStrategy(Enum):
    """Available processing strategies"""
    FIFO = "fifo"  # First in, first out
    PRIORITY = "priority"  # Process by priority
    SMART = "smart"  # Smart processing based on various factors

class QueueStats(TypedDict):
    """Type definition for queue statistics"""
    total_processed: int
    successful: int
    failed: int
    success_rate: float
    average_processing_time: float
    error_counts: Dict[str, int]
    last_processed: Optional[str]

class QueueMetrics:
    """Tracks queue processing metrics"""

    MAX_PROCESSING_TIME: ClassVar[float] = 3600.0  # 1 hour in seconds

    def __init__(self) -> None:
        self.total_processed = 0
        self.successful = 0
        self.failed = 0
        self.processing_times: List[float] = []
        self.errors: Dict[str, int] = {}
        self.last_processed: Optional[datetime] = None

    def record_success(self, processing_time: float) -> None:
        """
        Record successful processing.
        
        Args:
            processing_time: Time taken to process in seconds
        """
        if processing_time > self.MAX_PROCESSING_TIME:
            logger.warning(f"Unusually long processing time: {processing_time} seconds")
        
        self.total_processed += 1
        self.successful += 1
        self.processing_times.append(processing_time)
        self.last_processed = datetime.utcnow()

    def record_failure(self, error: str) -> None:
        """
        Record processing failure.
        
        Args:
            error: Error message describing the failure
        """
        self.total_processed += 1
        self.failed += 1
        self.errors[error] = self.errors.get(error, 0) + 1
        self.last_processed = datetime.utcnow()

    def get_stats(self) -> QueueStats:
        """
        Get queue metrics.
        
        Returns:
            Dictionary containing queue statistics
        """
        avg_time = (
            sum(self.processing_times) / len(self.processing_times)
            if self.processing_times
            else 0
        )
        return QueueStats(
            total_processed=self.total_processed,
            successful=self.successful,
            failed=self.failed,
            success_rate=(
                self.successful / self.total_processed
                if self.total_processed > 0
                else 0
            ),
            average_processing_time=avg_time,
            error_counts=self.errors.copy(),
            last_processed=self.last_processed.isoformat() if self.last_processed else None
        )

class QueueProcessor:
    """Handles adding videos to the processing queue"""

    def __init__(
        self,
        queue_manager: EnhancedVideoQueueManager,
        strategy: ProcessingStrategy = ProcessingStrategy.SMART,
        max_retries: int = 3
    ) -> None:
        self.queue_manager = queue_manager
        self.strategy = strategy
        self.max_retries = max_retries
        self.metrics = QueueMetrics()
        self._processing: Set[str] = set()
        self._processing_lock = asyncio.Lock()

    async def process_urls(
        self,
        message: discord.Message,
        urls: Union[List[str], Set[str], List[URLMetadata]],
        priority: QueuePriority = QueuePriority.NORMAL
    ) -> None:
        """
        Process extracted URLs by adding them to the queue.
        
        Args:
            message: Discord message containing the URLs
            urls: List or set of URLs or URLMetadata objects to process
            priority: Priority level for queue processing
            
        Raises:
            QueueProcessingError: If there's an error adding URLs to the queue
        """
        processed_urls: Set[str] = set()
        
        for url_data in urls:
            url = url_data.url if isinstance(url_data, URLMetadata) else url_data
            
            if url in processed_urls:
                logger.debug(f"Skipping duplicate URL: {url}")
                continue
                
            try:
                logger.info(f"Adding URL to queue: {url}")
                await message.add_reaction(REACTIONS['queued'])

                # Create queue item
                item = QueueItem(
                    url=url,
                    message_id=message.id,
                    channel_id=message.channel.id,
                    guild_id=message.guild.id,
                    author_id=message.author.id,
                    priority=priority.value,
                    added_at=datetime.utcnow()
                )

                # Add to queue with appropriate strategy
                await self._add_to_queue(item)
                processed_urls.add(url)
                logger.info(f"Successfully added video to queue: {url}")

            except Exception as e:
                logger.error(f"Failed to add video to queue: {str(e)}", exc_info=True)
                await message.add_reaction(REACTIONS['error'])
                raise QueueProcessingError(f"Failed to add URL to queue: {str(e)}")

    async def _add_to_queue(self, item: QueueItem) -> None:
        """
        Add item to queue using current strategy.
        
        Args:
            item: Queue item to add
            
        Raises:
            QueueProcessingError: If there's an error adding the item
        """
        async with self._processing_lock:
            if item.url in self._processing:
                logger.debug(f"URL already being processed: {item.url}")
                return

            self._processing.add(item.url)

        try:
            # Apply processing strategy
            if self.strategy == ProcessingStrategy.PRIORITY:
                await self._add_with_priority(item)
            elif self.strategy == ProcessingStrategy.SMART:
                await self._add_with_smart_strategy(item)
            else:  # FIFO
                await self._add_fifo(item)

        except Exception as e:
            logger.error(f"Error adding item to queue: {e}", exc_info=True)
            raise QueueProcessingError(f"Failed to add item to queue: {str(e)}")
        finally:
            async with self._processing_lock:
                self._processing.remove(item.url)

    async def _add_with_priority(self, item: QueueItem) -> None:
        """Add item with priority handling"""
        await self.queue_manager.add_to_queue(
            url=item.url,
            message_id=item.message_id,
            channel_id=item.channel_id,
            guild_id=item.guild_id,
            author_id=item.author_id,
            priority=item.priority
        )

    async def _add_with_smart_strategy(self, item: QueueItem) -> None:
        """Add item using smart processing strategy"""
        priority = await self._calculate_smart_priority(item)
        
        await self.queue_manager.add_to_queue(
            url=item.url,
            message_id=item.message_id,
            channel_id=item.channel_id,
            guild_id=item.guild_id,
            author_id=item.author_id,
            priority=priority
        )

    async def _add_fifo(self, item: QueueItem) -> None:
        """Add item using FIFO strategy"""
        await self.queue_manager.add_to_queue(
            url=item.url,
            message_id=item.message_id,
            channel_id=item.channel_id,
            guild_id=item.guild_id,
            author_id=item.author_id,
            priority=QueuePriority.NORMAL.value
        )

    async def _calculate_smart_priority(self, item: QueueItem) -> int:
        """
        Calculate priority using smart strategy.
        
        Args:
            item: Queue item to calculate priority for
            
        Returns:
            Calculated priority value
        """
        base_priority = item.priority
        
        # Adjust based on queue metrics
        stats = self.metrics.get_stats()
        if stats["total_processed"] > 0:
            # Boost priority if queue is processing efficiently
            if stats["success_rate"] > 0.9:  # 90% success rate
                base_priority -= 1
            # Lower priority if having issues
            elif stats["success_rate"] < 0.5:  # 50% success rate
                base_priority += 1

        # Adjust based on retries
        if item.retry_count > 0:
            base_priority += item.retry_count

        # Ensure priority stays in valid range
        return max(0, min(base_priority, len(QueuePriority) - 1))

    async def format_archive_message(
        self,
        author: Optional[discord.Member],
        channel: discord.TextChannel,
        url: str
    ) -> str:
        """
        Format message for archive channel.
        
        Args:
            author: Optional message author
            channel: Channel the message was posted in
            url: URL being archived
            
        Returns:
            Formatted message string
        """
        author_mention = author.mention if author else "Unknown User"
        channel_mention = channel.mention if channel else "Unknown Channel"
        
        return (
            f"Video archived from {author_mention} in {channel_mention}\n"
            f"Original URL: {url}"
        )

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get queue processing metrics.
        
        Returns:
            Dictionary containing queue metrics and status
        """
        return {
            "metrics": self.metrics.get_stats(),
            "strategy": self.strategy.value,
            "active_processing": len(self._processing),
            "max_retries": self.max_retries
        }
