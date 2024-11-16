"""Queue processing functionality for video processing"""

import logging
import asyncio
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Set
from datetime import datetime
import discord

from .reactions import REACTIONS

logger = logging.getLogger("VideoArchiver")

class QueuePriority(Enum):
    """Queue item priorities"""
    HIGH = 0
    NORMAL = 1
    LOW = 2

@dataclass
class QueueItem:
    """Represents an item in the processing queue"""
    url: str
    message_id: int
    channel_id: int
    guild_id: int
    author_id: int
    priority: QueuePriority
    added_at: datetime
    metadata: Optional[Dict[str, Any]] = None
    attempts: int = 0
    last_attempt: Optional[datetime] = None
    error: Optional[str] = None

class ProcessingStrategy(Enum):
    """Available processing strategies"""
    FIFO = "fifo"  # First in, first out
    PRIORITY = "priority"  # Process by priority
    SMART = "smart"  # Smart processing based on various factors

class QueueMetrics:
    """Tracks queue processing metrics"""

    def __init__(self):
        self.total_processed = 0
        self.successful = 0
        self.failed = 0
        self.processing_times: List[float] = []
        self.errors: Dict[str, int] = {}
        self.last_processed: Optional[datetime] = None

    def record_success(self, processing_time: float) -> None:
        """Record successful processing"""
        self.total_processed += 1
        self.successful += 1
        self.processing_times.append(processing_time)
        self.last_processed = datetime.utcnow()

    def record_failure(self, error: str) -> None:
        """Record processing failure"""
        self.total_processed += 1
        self.failed += 1
        self.errors[error] = self.errors.get(error, 0) + 1
        self.last_processed = datetime.utcnow()

    def get_stats(self) -> Dict[str, Any]:
        """Get queue metrics"""
        avg_time = (
            sum(self.processing_times) / len(self.processing_times)
            if self.processing_times
            else 0
        )
        return {
            "total_processed": self.total_processed,
            "successful": self.successful,
            "failed": self.failed,
            "success_rate": (
                self.successful / self.total_processed
                if self.total_processed > 0
                else 0
            ),
            "average_processing_time": avg_time,
            "error_counts": self.errors.copy(),
            "last_processed": self.last_processed
        }

class QueueProcessor:
    """Handles adding videos to the processing queue"""

    def __init__(
        self,
        queue_manager,
        strategy: ProcessingStrategy = ProcessingStrategy.SMART,
        max_retries: int = 3
    ):
        self.queue_manager = queue_manager
        self.strategy = strategy
        self.max_retries = max_retries
        self.metrics = QueueMetrics()
        self._processing: Set[str] = set()
        self._processing_lock = asyncio.Lock()

    async def process_urls(
        self,
        message: discord.Message,
        urls: List[str],
        priority: QueuePriority = QueuePriority.NORMAL
    ) -> None:
        """Process extracted URLs by adding them to the queue"""
        for url in urls:
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
                    priority=priority,
                    added_at=datetime.utcnow()
                )

                # Add to queue with appropriate strategy
                await self._add_to_queue(item)
                logger.info(f"Successfully added video to queue: {url}")

            except Exception as e:
                logger.error(f"Failed to add video to queue: {str(e)}")
                await message.add_reaction(REACTIONS['error'])
                continue

    async def _add_to_queue(self, item: QueueItem) -> None:
        """Add item to queue using current strategy"""
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
            priority=item.priority.value
        )

    async def _add_with_smart_strategy(self, item: QueueItem) -> None:
        """Add item using smart processing strategy"""
        # Calculate priority based on various factors
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
        """Calculate priority using smart strategy"""
        base_priority = item.priority.value
        
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
        if item.attempts > 0:
            base_priority += item.attempts

        # Ensure priority stays in valid range
        return max(0, min(base_priority, len(QueuePriority) - 1))

    async def format_archive_message(
        self,
        author: Optional[discord.Member],
        channel: discord.TextChannel,
        url: str
    ) -> str:
        """Format message for archive channel"""
        author_mention = author.mention if author else "Unknown User"
        channel_mention = channel.mention if channel else "Unknown Channel"
        
        return (
            f"Video archived from {author_mention} in {channel_mention}\n"
            f"Original URL: {url}"
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Get queue processing metrics"""
        return {
            "metrics": self.metrics.get_stats(),
            "strategy": self.strategy.value,
            "active_processing": len(self._processing),
            "max_retries": self.max_retries
        }
