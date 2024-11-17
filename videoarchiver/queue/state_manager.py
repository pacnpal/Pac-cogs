"""Module for managing queue state"""

import logging
import asyncio
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Set, List, Optional, Any
from datetime import datetime

from videoarchiver.queue.models import QueueItem, QueueMetrics

logger = logging.getLogger("QueueStateManager")

class ItemState(Enum):
    """Possible states for queue items"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"

@dataclass
class StateTransition:
    """Records a state transition"""
    item_url: str
    from_state: ItemState
    to_state: ItemState
    timestamp: datetime
    reason: Optional[str] = None

class StateSnapshot:
    """Represents a point-in-time snapshot of queue state"""

    def __init__(self):
        self.timestamp = datetime.utcnow()
        self.queue: List[QueueItem] = []
        self.processing: Dict[str, QueueItem] = {}
        self.completed: Dict[str, QueueItem] = {}
        self.failed: Dict[str, QueueItem] = {}
        self.guild_queues: Dict[int, Set[str]] = {}
        self.channel_queues: Dict[int, Set[str]] = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "queue": [item.__dict__ for item in self.queue],
            "processing": {url: item.__dict__ for url, item in self.processing.items()},
            "completed": {url: item.__dict__ for url, item in self.completed.items()},
            "failed": {url: item.__dict__ for url, item in self.failed.items()},
            "guild_queues": {gid: list(urls) for gid, urls in self.guild_queues.items()},
            "channel_queues": {cid: list(urls) for cid, urls in self.channel_queues.items()}
        }

class StateValidator:
    """Validates queue state"""

    @staticmethod
    def validate_item(item: QueueItem) -> bool:
        """Validate a queue item"""
        return all([
            isinstance(item.url, str) and item.url,
            isinstance(item.guild_id, int) and item.guild_id > 0,
            isinstance(item.channel_id, int) and item.channel_id > 0,
            isinstance(item.priority, int) and 0 <= item.priority <= 10,
            isinstance(item.added_at, datetime),
            isinstance(item.status, str)
        ])

    @staticmethod
    def validate_transition(
        item: QueueItem,
        from_state: ItemState,
        to_state: ItemState
    ) -> bool:
        """Validate a state transition"""
        valid_transitions = {
            ItemState.PENDING: {ItemState.PROCESSING, ItemState.FAILED},
            ItemState.PROCESSING: {ItemState.COMPLETED, ItemState.FAILED, ItemState.RETRYING},
            ItemState.FAILED: {ItemState.RETRYING},
            ItemState.RETRYING: {ItemState.PENDING},
            ItemState.COMPLETED: set()  # No transitions from completed
        }
        return to_state in valid_transitions.get(from_state, set())

class StateTracker:
    """Tracks state changes and transitions"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.transitions: List[StateTransition] = []
        self.snapshots: List[StateSnapshot] = []
        self.state_counts: Dict[ItemState, int] = {state: 0 for state in ItemState}

    def record_transition(
        self,
        transition: StateTransition
    ) -> None:
        """Record a state transition"""
        self.transitions.append(transition)
        if len(self.transitions) > self.max_history:
            self.transitions.pop(0)
        
        self.state_counts[transition.from_state] -= 1
        self.state_counts[transition.to_state] += 1

    def take_snapshot(self, state_manager: 'QueueStateManager') -> None:
        """Take a snapshot of current state"""
        snapshot = StateSnapshot()
        snapshot.queue = state_manager._queue.copy()
        snapshot.processing = state_manager._processing.copy()
        snapshot.completed = state_manager._completed.copy()
        snapshot.failed = state_manager._failed.copy()
        snapshot.guild_queues = {
            gid: urls.copy() for gid, urls in state_manager._guild_queues.items()
        }
        snapshot.channel_queues = {
            cid: urls.copy() for cid, urls in state_manager._channel_queues.items()
        }
        
        self.snapshots.append(snapshot)
        if len(self.snapshots) > self.max_history:
            self.snapshots.pop(0)

    def get_state_history(self) -> Dict[str, Any]:
        """Get state history statistics"""
        return {
            "transitions": len(self.transitions),
            "snapshots": len(self.snapshots),
            "state_counts": {
                state.value: count
                for state, count in self.state_counts.items()
            },
            "latest_snapshot": (
                self.snapshots[-1].to_dict()
                if self.snapshots
                else None
            )
        }

class QueueStateManager:
    """Manages the state of the queue system"""

    def __init__(self, max_queue_size: int = 1000):
        self.max_queue_size = max_queue_size
        
        # Queue storage
        self._queue: List[QueueItem] = []
        self._processing: Dict[str, QueueItem] = {}
        self._completed: Dict[str, QueueItem] = {}
        self._failed: Dict[str, QueueItem] = {}

        # Tracking
        self._guild_queues: Dict[int, Set[str]] = {}
        self._channel_queues: Dict[int, Set[str]] = {}
        
        # State management
        self._lock = asyncio.Lock()
        self.validator = StateValidator()
        self.tracker = StateTracker()

    async def add_item(self, item: QueueItem) -> bool:
        """Add an item to the queue"""
        if not self.validator.validate_item(item):
            logger.error(f"Invalid queue item: {item}")
            return False

        async with self._lock:
            if len(self._queue) >= self.max_queue_size:
                return False

            # Record transition
            self.tracker.record_transition(StateTransition(
                item_url=item.url,
                from_state=ItemState.PENDING,
                to_state=ItemState.PENDING,
                timestamp=datetime.utcnow(),
                reason="Initial add"
            ))

            # Add to main queue
            self._queue.append(item)
            self._queue.sort(key=lambda x: (-x.priority, x.added_at))

            # Update tracking
            if item.guild_id not in self._guild_queues:
                self._guild_queues[item.guild_id] = set()
            self._guild_queues[item.guild_id].add(item.url)

            if item.channel_id not in self._channel_queues:
                self._channel_queues[item.channel_id] = set()
            self._channel_queues[item.channel_id].add(item.url)

            # Take snapshot periodically
            if len(self._queue) % 100 == 0:
                self.tracker.take_snapshot(self)

            return True

    async def get_next_items(self, count: int = 5) -> List[QueueItem]:
        """Get the next batch of items to process"""
        items = []
        async with self._lock:
            while len(items) < count and self._queue:
                item = self._queue.pop(0)
                items.append(item)
                self._processing[item.url] = item
                
                # Record transition
                self.tracker.record_transition(StateTransition(
                    item_url=item.url,
                    from_state=ItemState.PENDING,
                    to_state=ItemState.PROCESSING,
                    timestamp=datetime.utcnow()
                ))

        return items

    async def mark_completed(
        self,
        item: QueueItem,
        success: bool,
        error: Optional[str] = None
    ) -> None:
        """Mark an item as completed or failed"""
        async with self._lock:
            self._processing.pop(item.url, None)
            
            to_state = ItemState.COMPLETED if success else ItemState.FAILED
            self.tracker.record_transition(StateTransition(
                item_url=item.url,
                from_state=ItemState.PROCESSING,
                to_state=to_state,
                timestamp=datetime.utcnow(),
                reason=error if error else None
            ))

            if success:
                self._completed[item.url] = item
            else:
                self._failed[item.url] = item

    async def retry_item(self, item: QueueItem) -> None:
        """Add an item back to the queue for retry"""
        if not self.validator.validate_transition(
            item,
            ItemState.FAILED,
            ItemState.RETRYING
        ):
            logger.error(f"Invalid retry transition for item: {item}")
            return

        async with self._lock:
            self._processing.pop(item.url, None)
            item.status = ItemState.PENDING.value
            item.last_retry = datetime.utcnow()
            item.priority = max(0, item.priority - 1)
            
            # Record transitions
            self.tracker.record_transition(StateTransition(
                item_url=item.url,
                from_state=ItemState.FAILED,
                to_state=ItemState.RETRYING,
                timestamp=datetime.utcnow()
            ))
            self.tracker.record_transition(StateTransition(
                item_url=item.url,
                from_state=ItemState.RETRYING,
                to_state=ItemState.PENDING,
                timestamp=datetime.utcnow()
            ))

            self._queue.append(item)
            self._queue.sort(key=lambda x: (-x.priority, x.added_at))

    async def get_guild_status(self, guild_id: int) -> Dict[str, int]:
        """Get queue status for a specific guild"""
        async with self._lock:
            return {
                "pending": len([
                    item for item in self._queue
                    if item.guild_id == guild_id
                ]),
                "processing": len([
                    item for item in self._processing.values()
                    if item.guild_id == guild_id
                ]),
                "completed": len([
                    item for item in self._completed.values()
                    if item.guild_id == guild_id
                ]),
                "failed": len([
                    item for item in self._failed.values()
                    if item.guild_id == guild_id
                ])
            }

    async def clear_state(self) -> None:
        """Clear all state data"""
        async with self._lock:
            self._queue.clear()
            self._processing.clear()
            self._completed.clear()
            self._failed.clear()
            self._guild_queues.clear()
            self._channel_queues.clear()
            
            # Take final snapshot before clearing
            self.tracker.take_snapshot(self)

    async def get_state_for_persistence(self) -> Dict[str, Any]:
        """Get current state for persistence"""
        async with self._lock:
            # Take snapshot before persistence
            self.tracker.take_snapshot(self)
            
            return {
                "queue": self._queue,
                "processing": self._processing,
                "completed": self._completed,
                "failed": self._failed,
                "history": self.tracker.get_state_history()
            }

    async def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore state from persisted data"""
        async with self._lock:
            self._queue = state.get("queue", [])
            self._processing = state.get("processing", {})
            self._completed = state.get("completed", {})
            self._failed = state.get("failed", {})

            # Validate restored items
            for item in self._queue:
                if not self.validator.validate_item(item):
                    logger.warning(f"Removing invalid restored item: {item}")
                    self._queue.remove(item)

            # Rebuild tracking
            self._rebuild_tracking()

    def _rebuild_tracking(self) -> None:
        """Rebuild guild and channel tracking from queue data"""
        self._guild_queues.clear()
        self._channel_queues.clear()

        for item in self._queue:
            if item.guild_id not in self._guild_queues:
                self._guild_queues[item.guild_id] = set()
            self._guild_queues[item.guild_id].add(item.url)

            if item.channel_id not in self._channel_queues:
                self._channel_queues[item.channel_id] = set()
            self._channel_queues[item.channel_id].add(item.url)

    def get_state_stats(self) -> Dict[str, Any]:
        """Get comprehensive state statistics"""
        return {
            "queue_size": len(self._queue),
            "processing_count": len(self._processing),
            "completed_count": len(self._completed),
            "failed_count": len(self._failed),
            "guild_count": len(self._guild_queues),
            "channel_count": len(self._channel_queues),
            "history": self.tracker.get_state_history()
        }
