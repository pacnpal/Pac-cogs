"""Module for cleaning queue tracking data"""

import logging
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Any, Optional
from datetime import datetime

from models import QueueItem

logger = logging.getLogger("TrackingCleaner")


class TrackingCleanupStrategy(Enum):
    """Tracking cleanup strategies"""

    AGGRESSIVE = "aggressive"  # Remove all invalid entries
    CONSERVATIVE = "conservative"  # Keep recent invalid entries
    BALANCED = "balanced"  # Balance between cleanup and retention


class TrackingType(Enum):
    """Types of tracking data"""

    GUILD = "guild"
    CHANNEL = "channel"
    URL = "url"


@dataclass
class TrackingCleanupConfig:
    """Configuration for tracking cleanup"""

    batch_size: int = 100
    retention_period: int = 3600  # 1 hour
    validate_urls: bool = True
    cleanup_empty: bool = True
    max_invalid_ratio: float = 0.5  # 50% invalid threshold


@dataclass
class TrackingCleanupResult:
    """Result of a tracking cleanup operation"""

    timestamp: datetime
    strategy: TrackingCleanupStrategy
    items_cleaned: int
    guilds_cleaned: int
    channels_cleaned: int
    duration: float
    initial_counts: Dict[str, int]
    final_counts: Dict[str, int]
    error: Optional[str] = None


class TrackingValidator:
    """Validates tracking data"""

    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL format"""
        try:
            return bool(url and isinstance(url, str) and "://" in url)
        except Exception:
            return False

    @staticmethod
    def validate_id(id_value: int) -> bool:
        """Validate ID format"""
        try:
            return bool(isinstance(id_value, int) and id_value > 0)
        except Exception:
            return False


class TrackingCleanupTracker:
    """Tracks cleanup operations"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.history: List[TrackingCleanupResult] = []
        self.total_items_cleaned = 0
        self.total_guilds_cleaned = 0
        self.total_channels_cleaned = 0
        self.last_cleanup: Optional[datetime] = None

    def record_cleanup(self, result: TrackingCleanupResult) -> None:
        """Record a cleanup operation"""
        self.history.append(result)
        if len(self.history) > self.max_history:
            self.history.pop(0)

        self.total_items_cleaned += result.items_cleaned
        self.total_guilds_cleaned += result.guilds_cleaned
        self.total_channels_cleaned += result.channels_cleaned
        self.last_cleanup = result.timestamp

    def get_stats(self) -> Dict[str, Any]:
        """Get cleanup statistics"""
        return {
            "total_cleanups": len(self.history),
            "total_items_cleaned": self.total_items_cleaned,
            "total_guilds_cleaned": self.total_guilds_cleaned,
            "total_channels_cleaned": self.total_channels_cleaned,
            "last_cleanup": (
                self.last_cleanup.isoformat() if self.last_cleanup else None
            ),
            "recent_cleanups": [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "strategy": r.strategy.value,
                    "items_cleaned": r.items_cleaned,
                    "guilds_cleaned": r.guilds_cleaned,
                    "channels_cleaned": r.channels_cleaned,
                    "duration": r.duration,
                }
                for r in self.history[-5:]  # Last 5 cleanups
            ],
        }


class TrackingCleaner:
    """Handles cleanup of queue tracking data"""

    def __init__(
        self,
        strategy: TrackingCleanupStrategy = TrackingCleanupStrategy.BALANCED,
        config: Optional[TrackingCleanupConfig] = None,
    ):
        self.strategy = strategy
        self.config = config or TrackingCleanupConfig()
        self.tracker = TrackingCleanupTracker()
        self.validator = TrackingValidator()

    async def cleanup_tracking(
        self,
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        queue: List[QueueItem],
        processing: Dict[str, QueueItem],
    ) -> Tuple[int, Dict[str, int]]:
        """Clean up tracking data"""
        start_time = datetime.utcnow()

        try:
            # Get initial counts
            initial_counts = self._get_tracking_counts(guild_queues, channel_queues)

            # Get valid URLs
            valid_urls = self._get_valid_urls(queue, processing)

            # Clean tracking data based on strategy
            items_cleaned = 0
            guilds_cleaned = 0
            channels_cleaned = 0

            if self.strategy == TrackingCleanupStrategy.AGGRESSIVE:
                cleaned = await self._aggressive_cleanup(
                    guild_queues, channel_queues, valid_urls
                )
            elif self.strategy == TrackingCleanupStrategy.CONSERVATIVE:
                cleaned = await self._conservative_cleanup(
                    guild_queues, channel_queues, valid_urls
                )
            else:  # BALANCED
                cleaned = await self._balanced_cleanup(
                    guild_queues, channel_queues, valid_urls
                )

            items_cleaned = cleaned[0]
            guilds_cleaned = cleaned[1]
            channels_cleaned = cleaned[2]

            # Get final counts
            final_counts = self._get_tracking_counts(guild_queues, channel_queues)

            # Record cleanup result
            duration = (datetime.utcnow() - start_time).total_seconds()
            result = TrackingCleanupResult(
                timestamp=datetime.utcnow(),
                strategy=self.strategy,
                items_cleaned=items_cleaned,
                guilds_cleaned=guilds_cleaned,
                channels_cleaned=channels_cleaned,
                duration=duration,
                initial_counts=initial_counts,
                final_counts=final_counts,
            )
            self.tracker.record_cleanup(result)

            logger.info(
                self.format_tracking_cleanup_report(
                    initial_counts, final_counts, duration
                )
            )
            return items_cleaned, initial_counts

        except Exception as e:
            logger.error(f"Error cleaning tracking data: {e}")
            self.tracker.record_cleanup(
                TrackingCleanupResult(
                    timestamp=datetime.utcnow(),
                    strategy=self.strategy,
                    items_cleaned=0,
                    guilds_cleaned=0,
                    channels_cleaned=0,
                    duration=0,
                    initial_counts={},
                    final_counts={},
                    error=str(e),
                )
            )
            raise

    async def _aggressive_cleanup(
        self,
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        valid_urls: Set[str],
    ) -> Tuple[int, int, int]:
        """Perform aggressive cleanup"""
        items_cleaned = 0
        guilds_cleaned = 0
        channels_cleaned = 0

        # Clean guild tracking
        guild_cleaned = await self._cleanup_guild_tracking(
            guild_queues, valid_urls, validate_all=True
        )
        items_cleaned += guild_cleaned[0]
        guilds_cleaned += guild_cleaned[1]

        # Clean channel tracking
        channel_cleaned = await self._cleanup_channel_tracking(
            channel_queues, valid_urls, validate_all=True
        )
        items_cleaned += channel_cleaned[0]
        channels_cleaned += channel_cleaned[1]

        return items_cleaned, guilds_cleaned, channels_cleaned

    async def _conservative_cleanup(
        self,
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        valid_urls: Set[str],
    ) -> Tuple[int, int, int]:
        """Perform conservative cleanup"""
        items_cleaned = 0
        guilds_cleaned = 0
        channels_cleaned = 0

        # Only clean if invalid ratio exceeds threshold
        for guild_id, urls in list(guild_queues.items()):
            invalid_ratio = len(urls - valid_urls) / len(urls) if urls else 0
            if invalid_ratio > self.config.max_invalid_ratio:
                cleaned = await self._cleanup_guild_tracking(
                    {guild_id: urls}, valid_urls, validate_all=False
                )
                items_cleaned += cleaned[0]
                guilds_cleaned += cleaned[1]

        for channel_id, urls in list(channel_queues.items()):
            invalid_ratio = len(urls - valid_urls) / len(urls) if urls else 0
            if invalid_ratio > self.config.max_invalid_ratio:
                cleaned = await self._cleanup_channel_tracking(
                    {channel_id: urls}, valid_urls, validate_all=False
                )
                items_cleaned += cleaned[0]
                channels_cleaned += cleaned[1]

        return items_cleaned, guilds_cleaned, channels_cleaned

    async def _balanced_cleanup(
        self,
        guild_queues: Dict[int, Set[str]],
        channel_queues: Dict[int, Set[str]],
        valid_urls: Set[str],
    ) -> Tuple[int, int, int]:
        """Perform balanced cleanup"""
        items_cleaned = 0
        guilds_cleaned = 0
        channels_cleaned = 0

        # Clean guild tracking with validation
        guild_cleaned = await self._cleanup_guild_tracking(
            guild_queues, valid_urls, validate_all=self.config.validate_urls
        )
        items_cleaned += guild_cleaned[0]
        guilds_cleaned += guild_cleaned[1]

        # Clean channel tracking with validation
        channel_cleaned = await self._cleanup_channel_tracking(
            channel_queues, valid_urls, validate_all=self.config.validate_urls
        )
        items_cleaned += channel_cleaned[0]
        channels_cleaned += channel_cleaned[1]

        return items_cleaned, guilds_cleaned, channels_cleaned

    async def _cleanup_guild_tracking(
        self,
        guild_queues: Dict[int, Set[str]],
        valid_urls: Set[str],
        validate_all: bool,
    ) -> Tuple[int, int]:
        """Clean up guild tracking data"""
        items_cleaned = 0
        guilds_cleaned = 0
        batch_count = 0

        for guild_id in list(guild_queues.keys()):
            if not self.validator.validate_id(guild_id):
                guild_queues.pop(guild_id)
                guilds_cleaned += 1
                continue

            original_size = len(guild_queues[guild_id])
            guild_queues[guild_id] = {
                url
                for url in guild_queues[guild_id]
                if (
                    (not validate_all or self.validator.validate_url(url))
                    and url in valid_urls
                )
            }
            items_cleaned += original_size - len(guild_queues[guild_id])

            if self.config.cleanup_empty and not guild_queues[guild_id]:
                guild_queues.pop(guild_id)
                guilds_cleaned += 1

            batch_count += 1
            if batch_count >= self.config.batch_size:
                await asyncio.sleep(0)  # Yield to event loop
                batch_count = 0

        logger.debug(f"Cleaned {items_cleaned} guild tracking items")
        return items_cleaned, guilds_cleaned

    async def _cleanup_channel_tracking(
        self,
        channel_queues: Dict[int, Set[str]],
        valid_urls: Set[str],
        validate_all: bool,
    ) -> Tuple[int, int]:
        """Clean up channel tracking data"""
        items_cleaned = 0
        channels_cleaned = 0
        batch_count = 0

        for channel_id in list(channel_queues.keys()):
            if not self.validator.validate_id(channel_id):
                channel_queues.pop(channel_id)
                channels_cleaned += 1
                continue

            original_size = len(channel_queues[channel_id])
            channel_queues[channel_id] = {
                url
                for url in channel_queues[channel_id]
                if (
                    (not validate_all or self.validator.validate_url(url))
                    and url in valid_urls
                )
            }
            items_cleaned += original_size - len(channel_queues[channel_id])

            if self.config.cleanup_empty and not channel_queues[channel_id]:
                channel_queues.pop(channel_id)
                channels_cleaned += 1

            batch_count += 1
            if batch_count >= self.config.batch_size:
                await asyncio.sleep(0)  # Yield to event loop
                batch_count = 0

        logger.debug(f"Cleaned {items_cleaned} channel tracking items")
        return items_cleaned, channels_cleaned

    def _get_valid_urls(
        self, queue: List[QueueItem], processing: Dict[str, QueueItem]
    ) -> Set[str]:
        """Get set of valid URLs"""
        valid_urls = {item.url for item in queue}
        valid_urls.update(processing.keys())
        return valid_urls

    def _get_tracking_counts(
        self, guild_queues: Dict[int, Set[str]], channel_queues: Dict[int, Set[str]]
    ) -> Dict[str, int]:
        """Get tracking data counts"""
        return {
            "guilds": len(guild_queues),
            "channels": len(channel_queues),
            "guild_urls": sum(len(urls) for urls in guild_queues.values()),
            "channel_urls": sum(len(urls) for urls in channel_queues.values()),
        }

    def format_tracking_cleanup_report(
        self,
        initial_counts: Dict[str, int],
        final_counts: Dict[str, int],
        duration: float,
    ) -> str:
        """Format a tracking cleanup report"""
        total_cleaned = (initial_counts["guild_urls"] - final_counts["guild_urls"]) + (
            initial_counts["channel_urls"] - final_counts["channel_urls"]
        )

        return (
            f"Tracking Cleanup Results:\n"
            f"Strategy: {self.strategy.value}\n"
            f"Duration: {duration:.2f}s\n"
            f"Items:\n"
            f"- Guild Queues: {initial_counts['guilds']} -> {final_counts['guilds']}\n"
            f"- Channel Queues: {initial_counts['channels']} -> {final_counts['channels']}\n"
            f"- Guild URLs: {initial_counts['guild_urls']} -> {final_counts['guild_urls']}\n"
            f"- Channel URLs: {initial_counts['channel_urls']} -> {final_counts['channel_urls']}\n"
            f"Total items cleaned: {total_cleaned}"
        )

    def get_cleaner_stats(self) -> Dict[str, Any]:
        """Get comprehensive cleaner statistics"""
        return {
            "strategy": self.strategy.value,
            "config": {
                "batch_size": self.config.batch_size,
                "retention_period": self.config.retention_period,
                "validate_urls": self.config.validate_urls,
                "cleanup_empty": self.config.cleanup_empty,
                "max_invalid_ratio": self.config.max_invalid_ratio,
            },
            "tracker": self.tracker.get_stats(),
        }
