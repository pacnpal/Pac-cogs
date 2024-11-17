"""Module for handling queue item recovery operations"""

import logging
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Any, Set
from datetime import datetime, timedelta

from .models import QueueItem

logger = logging.getLogger("QueueRecoveryManager")

class RecoveryStrategy(Enum):
    """Recovery strategies"""
    RETRY = "retry"          # Retry the item
    FAIL = "fail"           # Mark as failed
    REQUEUE = "requeue"     # Add back to queue
    EMERGENCY = "emergency" # Emergency recovery

class RecoveryPolicy(Enum):
    """Recovery policies"""
    AGGRESSIVE = "aggressive"  # Recover quickly, more retries
    CONSERVATIVE = "conservative"  # Recover slowly, fewer retries
    BALANCED = "balanced"    # Balance between speed and reliability

@dataclass
class RecoveryThresholds:
    """Thresholds for recovery operations"""
    max_retries: int = 3
    deadlock_threshold: int = 300  # 5 minutes
    emergency_threshold: int = 600  # 10 minutes
    backoff_base: int = 5         # Base delay for exponential backoff
    max_concurrent_recoveries: int = 5

@dataclass
class RecoveryResult:
    """Result of a recovery operation"""
    item_url: str
    strategy: RecoveryStrategy
    success: bool
    error: Optional[str] = None
    retry_count: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)

class RecoveryTracker:
    """Tracks recovery operations"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.history: List[RecoveryResult] = []
        self.active_recoveries: Set[str] = set()
        self.recovery_counts: Dict[str, int] = {}
        self.success_counts: Dict[str, int] = {}
        self.error_counts: Dict[str, int] = {}

    def record_recovery(self, result: RecoveryResult) -> None:
        """Record a recovery operation"""
        self.history.append(result)
        if len(self.history) > self.max_history:
            self.history.pop(0)

        self.recovery_counts[result.item_url] = (
            self.recovery_counts.get(result.item_url, 0) + 1
        )

        if result.success:
            self.success_counts[result.item_url] = (
                self.success_counts.get(result.item_url, 0) + 1
            )
        else:
            self.error_counts[result.item_url] = (
                self.error_counts.get(result.item_url, 0) + 1
            )

    def start_recovery(self, url: str) -> None:
        """Start tracking a recovery operation"""
        self.active_recoveries.add(url)

    def end_recovery(self, url: str) -> None:
        """End tracking a recovery operation"""
        self.active_recoveries.discard(url)

    def get_stats(self) -> Dict[str, Any]:
        """Get recovery statistics"""
        return {
            "total_recoveries": len(self.history),
            "active_recoveries": len(self.active_recoveries),
            "success_rate": (
                sum(self.success_counts.values()) /
                len(self.history) if self.history else 0
            ),
            "recovery_counts": self.recovery_counts.copy(),
            "error_counts": self.error_counts.copy(),
            "recent_recoveries": [
                {
                    "url": r.item_url,
                    "strategy": r.strategy.value,
                    "success": r.success,
                    "error": r.error,
                    "timestamp": r.timestamp.isoformat()
                }
                for r in self.history[-10:]  # Last 10 recoveries
            ]
        }

class RecoveryManager:
    """Handles recovery of stuck or failed queue items"""

    def __init__(
        self,
        thresholds: Optional[RecoveryThresholds] = None,
        policy: RecoveryPolicy = RecoveryPolicy.BALANCED
    ):
        self.thresholds = thresholds or RecoveryThresholds()
        self.policy = policy
        self.tracker = RecoveryTracker()
        self._recovery_lock = asyncio.Lock()

    async def recover_stuck_items(
        self,
        stuck_items: List[Tuple[str, QueueItem]],
        state_manager,
        metrics_manager
    ) -> Tuple[int, int]:
        """Recover stuck items"""
        recovered = 0
        failed = 0

        try:
            async with self._recovery_lock:
                for url, item in stuck_items:
                    if len(self.tracker.active_recoveries) >= self.thresholds.max_concurrent_recoveries:
                        logger.warning("Max concurrent recoveries reached, waiting...")
                        await asyncio.sleep(1)
                        continue

                    try:
                        self.tracker.start_recovery(url)
                        strategy = self._determine_strategy(item)
                        
                        success = await self._execute_recovery(
                            url,
                            item,
                            strategy,
                            state_manager,
                            metrics_manager
                        )

                        if success:
                            recovered += 1
                        else:
                            failed += 1

                    except Exception as e:
                        logger.error(f"Error recovering item {url}: {str(e)}")
                        failed += 1
                    finally:
                        self.tracker.end_recovery(url)

            logger.info(f"Recovery complete - Recovered: {recovered}, Failed: {failed}")
            return recovered, failed

        except Exception as e:
            logger.error(f"Error in recovery process: {str(e)}")
            return 0, len(stuck_items)

    def _determine_strategy(self, item: QueueItem) -> RecoveryStrategy:
        """Determine recovery strategy based on item state"""
        if item.retry_count >= self.thresholds.max_retries:
            return RecoveryStrategy.FAIL

        processing_time = (
            datetime.utcnow().timestamp() - item.start_time
            if item.start_time
            else 0
        )

        if processing_time > self.thresholds.emergency_threshold:
            return RecoveryStrategy.EMERGENCY
        elif self.policy == RecoveryPolicy.AGGRESSIVE:
            return RecoveryStrategy.RETRY
        elif self.policy == RecoveryPolicy.CONSERVATIVE:
            return RecoveryStrategy.REQUEUE
        else:  # BALANCED
            return (
                RecoveryStrategy.RETRY
                if item.retry_count < self.thresholds.max_retries // 2
                else RecoveryStrategy.REQUEUE
            )

    async def _execute_recovery(
        self,
        url: str,
        item: QueueItem,
        strategy: RecoveryStrategy,
        state_manager,
        metrics_manager
    ) -> bool:
        """Execute recovery strategy"""
        try:
            if strategy == RecoveryStrategy.FAIL:
                await self._handle_failed_item(url, item, state_manager, metrics_manager)
                success = False
            elif strategy == RecoveryStrategy.RETRY:
                await self._handle_retry_item(url, item, state_manager)
                success = True
            elif strategy == RecoveryStrategy.REQUEUE:
                await self._handle_requeue_item(url, item, state_manager)
                success = True
            else:  # EMERGENCY
                await self._handle_emergency_recovery(url, item, state_manager, metrics_manager)
                success = True

            self.tracker.record_recovery(RecoveryResult(
                item_url=url,
                strategy=strategy,
                success=success,
                retry_count=item.retry_count
            ))

            return success

        except Exception as e:
            self.tracker.record_recovery(RecoveryResult(
                item_url=url,
                strategy=strategy,
                success=False,
                error=str(e),
                retry_count=item.retry_count
            ))
            raise

    async def _handle_failed_item(
        self,
        url: str,
        item: QueueItem,
        state_manager,
        metrics_manager
    ) -> None:
        """Handle an item that has exceeded retry attempts"""
        logger.warning(f"Moving stuck item to failed: {url}")
        
        item.status = "failed"
        item.error = "Exceeded maximum retries after being stuck"
        item.last_error = item.error
        item.last_error_time = datetime.utcnow()
        
        await state_manager.mark_completed(item, False, item.error)
        metrics_manager.update(
            processing_time=item.processing_time or 0,
            success=False,
            error=item.error
        )

    async def _handle_retry_item(
        self,
        url: str,
        item: QueueItem,
        state_manager
    ) -> None:
        """Handle an item that will be retried"""
        logger.info(f"Recovering stuck item for retry: {url}")
        
        item.retry_count += 1
        item.start_time = None
        item.processing_time = 0
        item.last_retry = datetime.utcnow()
        item.status = "pending"
        item.priority = max(0, item.priority - 2)
        
        await state_manager.retry_item(item)

    async def _handle_requeue_item(
        self,
        url: str,
        item: QueueItem,
        state_manager
    ) -> None:
        """Handle an item that will be requeued"""
        logger.info(f"Requeuing stuck item: {url}")
        
        item.retry_count += 1
        item.start_time = None
        item.processing_time = 0
        item.last_retry = datetime.utcnow()
        item.status = "pending"
        item.priority = 0  # Reset priority
        
        # Calculate backoff delay
        backoff = self.thresholds.backoff_base * (2 ** (item.retry_count - 1))
        await asyncio.sleep(min(backoff, 60))  # Cap at 60 seconds
        
        await state_manager.retry_item(item)

    async def _handle_emergency_recovery(
        self,
        url: str,
        item: QueueItem,
        state_manager,
        metrics_manager
    ) -> None:
        """Handle emergency recovery of an item"""
        logger.warning(f"Emergency recovery for item: {url}")
        
        # Force item cleanup
        await state_manager.force_cleanup_item(item)
        
        # Reset item state
        item.retry_count = 0
        item.start_time = None
        item.processing_time = 0
        item.status = "pending"
        item.priority = 10  # High priority
        
        # Add back to queue
        await state_manager.retry_item(item)

    async def perform_emergency_recovery(
        self,
        state_manager,
        metrics_manager
    ) -> None:
        """Perform emergency recovery of all processing items"""
        try:
            logger.warning("Performing emergency recovery of all processing items")
            
            processing_items = await state_manager.get_all_processing_items()
            
            recovered, failed = await self.recover_stuck_items(
                [(item.url, item) for item in processing_items],
                state_manager,
                metrics_manager
            )
            
            logger.info(f"Emergency recovery complete - Recovered: {recovered}, Failed: {failed}")
            
        except Exception as e:
            logger.error(f"Error during emergency recovery: {str(e)}")

    def should_recover_item(self, item: QueueItem) -> bool:
        """Check if an item should be recovered"""
        if not hasattr(item, 'start_time') or not item.start_time:
            return False

        processing_time = datetime.utcnow().timestamp() - item.start_time
        return processing_time > self.thresholds.deadlock_threshold

    def get_recovery_stats(self) -> Dict[str, Any]:
        """Get recovery statistics"""
        return {
            "policy": self.policy.value,
            "thresholds": {
                "max_retries": self.thresholds.max_retries,
                "deadlock_threshold": self.thresholds.deadlock_threshold,
                "emergency_threshold": self.thresholds.emergency_threshold,
                "max_concurrent": self.thresholds.max_concurrent_recoveries
            },
            "tracker": self.tracker.get_stats()
        }
