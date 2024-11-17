"""Module for cleaning historical queue items"""

import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any, Set
from datetime import datetime, timedelta

from videoarchiver.queue.models import QueueItem

logger = logging.getLogger("HistoryCleaner")

class CleanupStrategy(Enum):
    """Cleanup strategies"""
    AGGRESSIVE = "aggressive"    # Remove more aggressively
    CONSERVATIVE = "conservative"  # Remove conservatively
    BALANCED = "balanced"       # Balance between retention and cleanup

class CleanupPolicy(Enum):
    """Cleanup policies"""
    AGE = "age"           # Clean based on age
    SIZE = "size"         # Clean based on size
    HYBRID = "hybrid"     # Consider both age and size

@dataclass
class CleanupThresholds:
    """Thresholds for cleanup operations"""
    max_history_age: int = 43200  # 12 hours
    max_completed_items: int = 10000
    max_failed_items: int = 5000
    min_retention_time: int = 3600  # 1 hour
    size_threshold: int = 100 * 1024 * 1024  # 100MB

@dataclass
class CleanupResult:
    """Result of a cleanup operation"""
    timestamp: datetime
    items_cleaned: int
    space_freed: int
    duration: float
    strategy: CleanupStrategy
    policy: CleanupPolicy
    details: Dict[str, Any] = field(default_factory=dict)

class CleanupTracker:
    """Tracks cleanup operations"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.history: List[CleanupResult] = []
        self.total_items_cleaned = 0
        self.total_space_freed = 0
        self.last_cleanup: Optional[datetime] = None

    def record_cleanup(self, result: CleanupResult) -> None:
        """Record a cleanup operation"""
        self.history.append(result)
        if len(self.history) > self.max_history:
            self.history.pop(0)
        
        self.total_items_cleaned += result.items_cleaned
        self.total_space_freed += result.space_freed
        self.last_cleanup = result.timestamp

    def get_stats(self) -> Dict[str, Any]:
        """Get cleanup statistics"""
        return {
            "total_cleanups": len(self.history),
            "total_items_cleaned": self.total_items_cleaned,
            "total_space_freed": self.total_space_freed,
            "last_cleanup": (
                self.last_cleanup.isoformat()
                if self.last_cleanup
                else None
            ),
            "recent_cleanups": [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "items_cleaned": r.items_cleaned,
                    "space_freed": r.space_freed,
                    "strategy": r.strategy.value,
                    "policy": r.policy.value
                }
                for r in self.history[-5:]  # Last 5 cleanups
            ]
        }

class HistoryCleaner:
    """Handles cleanup of historical queue items"""

    def __init__(
        self,
        strategy: CleanupStrategy = CleanupStrategy.BALANCED,
        policy: CleanupPolicy = CleanupPolicy.HYBRID,
        thresholds: Optional[CleanupThresholds] = None
    ):
        self.strategy = strategy
        self.policy = policy
        self.thresholds = thresholds or CleanupThresholds()
        self.tracker = CleanupTracker()

    def _normalize_datetime(self, dt_value: any) -> datetime:
        """Normalize a datetime value"""
        current_time = datetime.utcnow()
        
        if not isinstance(dt_value, datetime):
            try:
                if isinstance(dt_value, str):
                    return datetime.fromisoformat(dt_value)
                else:
                    return current_time
            except (ValueError, TypeError):
                return current_time
        return dt_value

    async def cleanup_completed(
        self,
        completed: Dict[str, QueueItem],
        cleanup_cutoff: datetime
    ) -> int:
        """Clean up completed items"""
        start_time = datetime.utcnow()
        items_cleaned = 0
        space_freed = 0
        completed_count = len(completed)

        try:
            # Determine cleanup approach based on strategy and policy
            if self.policy == CleanupPolicy.SIZE:
                items_to_clean = self._get_items_by_size(completed)
            elif self.policy == CleanupPolicy.HYBRID:
                items_to_clean = self._get_items_hybrid(completed, cleanup_cutoff)
            else:  # AGE policy
                items_to_clean = self._get_items_by_age(completed, cleanup_cutoff)

            # Clean items
            for url in items_to_clean:
                try:
                    item = completed[url]
                    space_freed += self._estimate_item_size(item)
                    completed.pop(url)
                    items_cleaned += 1
                except Exception as e:
                    logger.error(f"Error cleaning completed item {url}: {e}")
                    completed.pop(url)
                    items_cleaned += 1

            # Record cleanup
            self._record_cleanup_result(
                items_cleaned,
                space_freed,
                start_time,
                "completed"
            )

            logger.debug(f"Cleaned {items_cleaned} completed items")
            return items_cleaned

        except Exception as e:
            logger.error(f"Error during completed items cleanup: {e}")
            return 0

    async def cleanup_failed(
        self,
        failed: Dict[str, QueueItem],
        cleanup_cutoff: datetime
    ) -> int:
        """Clean up failed items"""
        start_time = datetime.utcnow()
        items_cleaned = 0
        space_freed = 0
        failed_count = len(failed)

        try:
            # Determine cleanup approach
            if self.policy == CleanupPolicy.SIZE:
                items_to_clean = self._get_items_by_size(failed)
            elif self.policy == CleanupPolicy.HYBRID:
                items_to_clean = self._get_items_hybrid(failed, cleanup_cutoff)
            else:  # AGE policy
                items_to_clean = self._get_items_by_age(failed, cleanup_cutoff)

            # Clean items
            for url in items_to_clean:
                try:
                    item = failed[url]
                    space_freed += self._estimate_item_size(item)
                    failed.pop(url)
                    items_cleaned += 1
                except Exception as e:
                    logger.error(f"Error cleaning failed item {url}: {e}")
                    failed.pop(url)
                    items_cleaned += 1

            # Record cleanup
            self._record_cleanup_result(
                items_cleaned,
                space_freed,
                start_time,
                "failed"
            )

            logger.debug(f"Cleaned {items_cleaned} failed items")
            return items_cleaned

        except Exception as e:
            logger.error(f"Error during failed items cleanup: {e}")
            return 0

    def _get_items_by_age(
        self,
        items: Dict[str, QueueItem],
        cutoff: datetime
    ) -> Set[str]:
        """Get items to clean based on age"""
        to_clean = set()
        
        for url, item in items.items():
            item.added_at = self._normalize_datetime(item.added_at)
            if item.added_at < cutoff:
                to_clean.add(url)

        return to_clean

    def _get_items_by_size(self, items: Dict[str, QueueItem]) -> Set[str]:
        """Get items to clean based on size"""
        to_clean = set()
        total_size = 0
        
        # Sort items by size estimate
        sorted_items = sorted(
            items.items(),
            key=lambda x: self._estimate_item_size(x[1]),
            reverse=True
        )
        
        for url, item in sorted_items:
            total_size += self._estimate_item_size(item)
            if total_size > self.thresholds.size_threshold:
                to_clean.add(url)

        return to_clean

    def _get_items_hybrid(
        self,
        items: Dict[str, QueueItem],
        cutoff: datetime
    ) -> Set[str]:
        """Get items to clean using hybrid approach"""
        by_age = self._get_items_by_age(items, cutoff)
        by_size = self._get_items_by_size(items)
        
        if self.strategy == CleanupStrategy.AGGRESSIVE:
            return by_age.union(by_size)
        elif self.strategy == CleanupStrategy.CONSERVATIVE:
            return by_age.intersection(by_size)
        else:  # BALANCED
            return by_age

    def _estimate_item_size(self, item: QueueItem) -> int:
        """Estimate size of an item in bytes"""
        # This could be enhanced with actual file size tracking
        base_size = 1024  # 1KB base size
        return base_size * (item.retry_count + 1)

    def _record_cleanup_result(
        self,
        items_cleaned: int,
        space_freed: int,
        start_time: datetime,
        cleanup_type: str
    ) -> None:
        """Record cleanup result"""
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        result = CleanupResult(
            timestamp=datetime.utcnow(),
            items_cleaned=items_cleaned,
            space_freed=space_freed,
            duration=duration,
            strategy=self.strategy,
            policy=self.policy,
            details={"type": cleanup_type}
        )
        
        self.tracker.record_cleanup(result)

    def get_cleanup_cutoff(self) -> datetime:
        """Get the cutoff time for cleanup"""
        if self.strategy == CleanupStrategy.AGGRESSIVE:
            age = self.thresholds.max_history_age // 2
        elif self.strategy == CleanupStrategy.CONSERVATIVE:
            age = self.thresholds.max_history_age * 2
        else:  # BALANCED
            age = self.thresholds.max_history_age

        return datetime.utcnow() - timedelta(seconds=max(
            age,
            self.thresholds.min_retention_time
        ))

    def format_cleanup_report(
        self,
        initial_completed: int,
        final_completed: int,
        initial_failed: int,
        final_failed: int
    ) -> str:
        """Format a cleanup report"""
        stats = self.tracker.get_stats()
        
        return (
            f"History Cleanup Results:\n"
            f"- Completed items: {initial_completed} -> {final_completed}\n"
            f"- Failed items: {initial_failed} -> {final_failed}\n"
            f"- Total items cleaned: {(initial_completed - final_completed) + (initial_failed - final_failed)}\n"
            f"- Space freed: {stats['total_space_freed']} bytes\n"
            f"- Strategy: {self.strategy.value}\n"
            f"- Policy: {self.policy.value}\n"
            f"- Total cleanups: {stats['total_cleanups']}"
        )

    def get_cleaner_stats(self) -> Dict[str, Any]:
        """Get comprehensive cleaner statistics"""
        return {
            "strategy": self.strategy.value,
            "policy": self.policy.value,
            "thresholds": {
                "max_history_age": self.thresholds.max_history_age,
                "max_completed_items": self.thresholds.max_completed_items,
                "max_failed_items": self.thresholds.max_failed_items,
                "min_retention_time": self.thresholds.min_retention_time,
                "size_threshold": self.thresholds.size_threshold
            },
            "tracker": self.tracker.get_stats()
        }
