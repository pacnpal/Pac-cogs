"""Module for cleaning guild-specific queue items"""

import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Any, Optional
from datetime import datetime

from ..models import QueueItem

logger = logging.getLogger("GuildCleaner")

class GuildCleanupStrategy(Enum):
    """Guild cleanup strategies"""
    FULL = "full"          # Clear all guild items
    SELECTIVE = "selective"  # Clear only specific categories
    GRACEFUL = "graceful"   # Clear with grace period

class CleanupCategory(Enum):
    """Categories for cleanup"""
    QUEUE = "queue"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TRACKING = "tracking"

@dataclass
class GuildCleanupConfig:
    """Configuration for guild cleanup"""
    categories: Set[CleanupCategory] = field(default_factory=lambda: set(CleanupCategory))
    grace_period: int = 300  # 5 minutes
    preserve_completed: bool = False
    preserve_failed: bool = False
    batch_size: int = 100

@dataclass
class GuildCleanupResult:
    """Result of a guild cleanup operation"""
    guild_id: int
    timestamp: datetime
    strategy: GuildCleanupStrategy
    items_cleared: int
    categories_cleared: Set[CleanupCategory]
    initial_counts: Dict[str, int]
    final_counts: Dict[str, int]
    duration: float
    error: Optional[str] = None

class GuildCleanupTracker:
    """Tracks guild cleanup operations"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.history: List[GuildCleanupResult] = []
        self.cleanup_counts: Dict[int, int] = {}  # guild_id -> count
        self.total_items_cleared = 0
        self.last_cleanup: Optional[datetime] = None

    def record_cleanup(self, result: GuildCleanupResult) -> None:
        """Record a cleanup operation"""
        self.history.append(result)
        if len(self.history) > self.max_history:
            self.history.pop(0)

        self.cleanup_counts[result.guild_id] = (
            self.cleanup_counts.get(result.guild_id, 0) + 1
        )
        self.total_items_cleared += result.items_cleared
        self.last_cleanup = result.timestamp

    def get_stats(self) -> Dict[str, Any]:
        """Get cleanup statistics"""
        return {
            "total_cleanups": len(self.history),
            "total_items_cleared": self.total_items_cleared,
            "guilds_cleaned": len(self.cleanup_counts),
            "last_cleanup": (
                self.last_cleanup.isoformat()
                if self.last_cleanup
                else None
            ),
            "recent_cleanups": [
                {
                    "guild_id": r.guild_id,
                    "timestamp": r.timestamp.isoformat(),
                    "strategy": r.strategy.value,
                    "items_cleared": r.items_cleared,
                    "categories": [c.value for c in r.categories_cleared]
                }
                for r in self.history[-5:]  # Last 5 cleanups
            ]
        }

class GuildCleaner:
    """Handles cleanup of guild-specific queue items"""

    def __init__(
        self,
        strategy: GuildCleanupStrategy = GuildCleanupStrategy.GRACEFUL,
        config: Optional[GuildCleanupConfig] = None
    ):
        self.strategy = strategy
        self.config = config or GuildCleanupConfig()
        self.tracker = GuildCleanupTracker()

    async def clear_guild_items(
        self,
        guild_id: int,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        completed: Dict[str, QueueItem],
        failed: Dict[str, QueueItem],
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]]
    ) -> Tuple[int, Dict[str, int]]:
        """Clear all queue items for a specific guild"""
        start_time = datetime.utcnow()
        cleared_categories = set()
        
        try:
            # Get initial counts
            initial_counts = self._get_item_counts(
                guild_id,
                queue,
                processing,
                completed,
                failed
            )

            # Get URLs for this guild
            guild_urls = guild_queues.get(guild_id, set())

            # Clear items based on strategy
            cleared_count = 0
            if self.strategy == GuildCleanupStrategy.FULL:
                cleared_count = await self._full_cleanup(
                    guild_id,
                    queue,
                    processing,
                    completed,
                    failed,
                    guild_queues,
                    channel_queues,
                    cleared_categories
                )
            elif self.strategy == GuildCleanupStrategy.SELECTIVE:
                cleared_count = await self._selective_cleanup(
                    guild_id,
                    queue,
                    processing,
                    completed,
                    failed,
                    guild_queues,
                    channel_queues,
                    cleared_categories
                )
            else:  # GRACEFUL
                cleared_count = await self._graceful_cleanup(
                    guild_id,
                    queue,
                    processing,
                    completed,
                    failed,
                    guild_queues,
                    channel_queues,
                    cleared_categories
                )

            # Get final counts
            final_counts = self._get_item_counts(
                guild_id,
                queue,
                processing,
                completed,
                failed
            )

            # Record cleanup result
            duration = (datetime.utcnow() - start_time).total_seconds()
            result = GuildCleanupResult(
                guild_id=guild_id,
                timestamp=datetime.utcnow(),
                strategy=self.strategy,
                items_cleared=cleared_count,
                categories_cleared=cleared_categories,
                initial_counts=initial_counts,
                final_counts=final_counts,
                duration=duration
            )
            self.tracker.record_cleanup(result)

            logger.info(self.format_guild_cleanup_report(
                guild_id,
                initial_counts,
                final_counts,
                duration
            ))
            return cleared_count, initial_counts

        except Exception as e:
            logger.error(f"Error clearing guild {guild_id} queue: {e}")
            self.tracker.record_cleanup(GuildCleanupResult(
                guild_id=guild_id,
                timestamp=datetime.utcnow(),
                strategy=self.strategy,
                items_cleared=0,
                categories_cleared=set(),
                initial_counts={},
                final_counts={},
                duration=0,
                error=str(e)
            ))
            raise

    async def _full_cleanup(
        self,
        guild_id: int,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        completed: Dict[str, QueueItem],
        failed: Dict[str, QueueItem],
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        cleared_categories: Set[CleanupCategory]
    ) -> int:
        """Perform full cleanup"""
        cleared_count = 0

        # Clear from pending queue
        queue[:] = [item for item in queue if item.guild_id != guild_id]
        cleared_count += len(queue)
        cleared_categories.add(CleanupCategory.QUEUE)

        # Clear from processing
        cleared = await self._clear_from_dict(
            processing, guild_id, 'processing'
        )
        cleared_count += cleared
        cleared_categories.add(CleanupCategory.PROCESSING)

        # Clear from completed
        cleared = await self._clear_from_dict(
            completed, guild_id, 'completed'
        )
        cleared_count += cleared
        cleared_categories.add(CleanupCategory.COMPLETED)

        # Clear from failed
        cleared = await self._clear_from_dict(
            failed, guild_id, 'failed'
        )
        cleared_count += cleared
        cleared_categories.add(CleanupCategory.FAILED)

        # Clear tracking
        cleared = await self._clear_tracking(
            guild_id,
            guild_queues,
            channel_queues
        )
        cleared_count += cleared
        cleared_categories.add(CleanupCategory.TRACKING)

        return cleared_count

    async def _selective_cleanup(
        self,
        guild_id: int,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        completed: Dict[str, QueueItem],
        failed: Dict[str, QueueItem],
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        cleared_categories: Set[CleanupCategory]
    ) -> int:
        """Perform selective cleanup"""
        cleared_count = 0

        # Clear only configured categories
        if CleanupCategory.QUEUE in self.config.categories:
            queue[:] = [item for item in queue if item.guild_id != guild_id]
            cleared_count += len(queue)
            cleared_categories.add(CleanupCategory.QUEUE)

        if CleanupCategory.PROCESSING in self.config.categories:
            cleared = await self._clear_from_dict(
                processing, guild_id, 'processing'
            )
            cleared_count += cleared
            cleared_categories.add(CleanupCategory.PROCESSING)

        if (
            CleanupCategory.COMPLETED in self.config.categories and
            not self.config.preserve_completed
        ):
            cleared = await self._clear_from_dict(
                completed, guild_id, 'completed'
            )
            cleared_count += cleared
            cleared_categories.add(CleanupCategory.COMPLETED)

        if (
            CleanupCategory.FAILED in self.config.categories and
            not self.config.preserve_failed
        ):
            cleared = await self._clear_from_dict(
                failed, guild_id, 'failed'
            )
            cleared_count += cleared
            cleared_categories.add(CleanupCategory.FAILED)

        if CleanupCategory.TRACKING in self.config.categories:
            cleared = await self._clear_tracking(
                guild_id,
                guild_queues,
                channel_queues
            )
            cleared_count += cleared
            cleared_categories.add(CleanupCategory.TRACKING)

        return cleared_count

    async def _graceful_cleanup(
        self,
        guild_id: int,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        completed: Dict[str, QueueItem],
        failed: Dict[str, QueueItem],
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        cleared_categories: Set[CleanupCategory]
    ) -> int:
        """Perform graceful cleanup"""
        cleared_count = 0
        cutoff_time = datetime.utcnow().timestamp() - self.config.grace_period

        # Clear queue items beyond grace period
        queue[:] = [
            item for item in queue
            if not (
                item.guild_id == guild_id and
                item.added_at.timestamp() < cutoff_time
            )
        ]
        cleared_count += len(queue)
        cleared_categories.add(CleanupCategory.QUEUE)

        # Clear processing items beyond grace period
        for url in list(processing.keys()):
            item = processing[url]
            if (
                item.guild_id == guild_id and
                item.added_at.timestamp() < cutoff_time
            ):
                processing.pop(url)
                cleared_count += 1
        cleared_categories.add(CleanupCategory.PROCESSING)

        # Clear completed and failed based on config
        if not self.config.preserve_completed:
            cleared = await self._clear_from_dict(
                completed, guild_id, 'completed'
            )
            cleared_count += cleared
            cleared_categories.add(CleanupCategory.COMPLETED)

        if not self.config.preserve_failed:
            cleared = await self._clear_from_dict(
                failed, guild_id, 'failed'
            )
            cleared_count += cleared
            cleared_categories.add(CleanupCategory.FAILED)

        # Clear tracking
        cleared = await self._clear_tracking(
            guild_id,
            guild_queues,
            channel_queues
        )
        cleared_count += cleared
        cleared_categories.add(CleanupCategory.TRACKING)

        return cleared_count

    async def _clear_from_dict(
        self,
        items_dict: Dict[str, QueueItem],
        guild_id: int,
        category: str
    ) -> int:
        """Clear guild items from a dictionary"""
        cleared = 0
        batch_count = 0
        
        for url in list(items_dict.keys()):
            if items_dict[url].guild_id == guild_id:
                items_dict.pop(url)
                cleared += 1
                batch_count += 1
                
                # Process in batches
                if batch_count >= self.config.batch_size:
                    await asyncio.sleep(0)  # Yield to event loop
                    batch_count = 0
        
        logger.debug(f"Cleared {cleared} {category} items for guild {guild_id}")
        return cleared

    async def _clear_tracking(
        self,
        guild_id: int,
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]]
    ) -> int:
        """Clear guild tracking data"""
        cleared = 0
        guild_urls = guild_queues.get(guild_id, set())
        
        # Clear guild tracking
        if guild_id in guild_queues:
            cleared += len(guild_queues[guild_id])
            guild_queues.pop(guild_id)

        # Clear channel tracking
        await self._clear_channel_tracking(channel_queues, guild_urls)
        
        return cleared

    async def _clear_channel_tracking(
        self,
        channel_queues: Dict[int, Set[str]],
        guild_urls: Set[str]
    ) -> None:
        """Clear channel tracking for guild URLs"""
        batch_count = 0
        
        for channel_id in list(channel_queues.keys()):
            channel_queues[channel_id] = {
                url for url in channel_queues[channel_id]
                if url not in guild_urls
            }
            if not channel_queues[channel_id]:
                channel_queues.pop(channel_id)
            
            batch_count += 1
            if batch_count >= self.config.batch_size:
                await asyncio.sleep(0)  # Yield to event loop
                batch_count = 0

    def _get_item_counts(
        self,
        guild_id: int,
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
        completed: Dict[str, QueueItem],
        failed: Dict[str, QueueItem]
    ) -> Dict[str, int]:
        """Get item counts for a guild"""
        return {
            'queue': len([item for item in queue if item.guild_id == guild_id]),
            'processing': len([item for item in processing.values() if item.guild_id == guild_id]),
            'completed': len([item for item in completed.values() if item.guild_id == guild_id]),
            'failed': len([item for item in failed.values() if item.guild_id == guild_id])
        }

    def format_guild_cleanup_report(
        self,
        guild_id: int,
        initial_counts: Dict[str, int],
        final_counts: Dict[str, int],
        duration: float
    ) -> str:
        """Format a guild cleanup report"""
        return (
            f"Guild {guild_id} Cleanup Results:\n"
            f"Strategy: {self.strategy.value}\n"
            f"Duration: {duration:.2f}s\n"
            f"Items:\n"
            f"- Queue: {initial_counts['queue']} -> {final_counts['queue']}\n"
            f"- Processing: {initial_counts['processing']} -> {final_counts['processing']}\n"
            f"- Completed: {initial_counts['completed']} -> {final_counts['completed']}\n"
            f"- Failed: {initial_counts['failed']} -> {final_counts['failed']}\n"
            f"Total cleared: {sum(initial_counts.values()) - sum(final_counts.values())} items"
        )

    def get_cleaner_stats(self) -> Dict[str, Any]:
        """Get comprehensive cleaner statistics"""
        return {
            "strategy": self.strategy.value,
            "config": {
                "categories": [c.value for c in self.config.categories],
                "grace_period": self.config.grace_period,
                "preserve_completed": self.config.preserve_completed,
                "preserve_failed": self.config.preserve_failed,
                "batch_size": self.config.batch_size
            },
            "tracker": self.tracker.get_stats()
        }
