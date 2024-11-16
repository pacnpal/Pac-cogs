"""Enhanced queue manager for video processing"""

import asyncio
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any, List, Set
from datetime import datetime, timedelta

from .state_manager import QueueStateManager
from .processor import QueueProcessor
from .metrics_manager import QueueMetricsManager
from .persistence import QueuePersistenceManager
from .monitoring import QueueMonitor, MonitoringLevel
from .cleanup import QueueCleaner
from .models import QueueItem, QueueError, CleanupError

logger = logging.getLogger("QueueManager")

class QueueState(Enum):
    """Queue operational states"""
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"

class QueueMode(Enum):
    """Queue processing modes"""
    NORMAL = "normal"      # Standard processing
    BATCH = "batch"       # Batch processing
    PRIORITY = "priority" # Priority-based processing
    MAINTENANCE = "maintenance"  # Maintenance mode

@dataclass
class QueueConfig:
    """Queue configuration settings"""
    max_retries: int = 3
    retry_delay: int = 5
    max_queue_size: int = 1000
    cleanup_interval: int = 3600  # 1 hour
    max_history_age: int = 86400  # 24 hours
    deadlock_threshold: int = 300  # 5 minutes
    check_interval: int = 60      # 1 minute
    batch_size: int = 10
    max_concurrent: int = 3
    persistence_enabled: bool = True
    monitoring_level: MonitoringLevel = MonitoringLevel.NORMAL

@dataclass
class QueueStats:
    """Queue statistics"""
    start_time: datetime = field(default_factory=datetime.utcnow)
    total_processed: int = 0
    total_failed: int = 0
    uptime: timedelta = field(default_factory=lambda: timedelta())
    peak_queue_size: int = 0
    peak_memory_usage: float = 0.0
    state_changes: List[Dict[str, Any]] = field(default_factory=list)

class QueueCoordinator:
    """Coordinates queue operations"""

    def __init__(self):
        self.state = QueueState.UNINITIALIZED
        self.mode = QueueMode.NORMAL
        self._state_lock = asyncio.Lock()
        self._mode_lock = asyncio.Lock()
        self._paused = asyncio.Event()
        self._paused.set()

    async def set_state(self, state: QueueState) -> None:
        """Set queue state"""
        async with self._state_lock:
            self.state = state

    async def set_mode(self, mode: QueueMode) -> None:
        """Set queue mode"""
        async with self._mode_lock:
            self.mode = mode

    async def pause(self) -> None:
        """Pause queue processing"""
        self._paused.clear()
        await self.set_state(QueueState.PAUSED)

    async def resume(self) -> None:
        """Resume queue processing"""
        self._paused.set()
        await self.set_state(QueueState.RUNNING)

    async def wait_if_paused(self) -> None:
        """Wait if queue is paused"""
        await self._paused.wait()

class EnhancedVideoQueueManager:
    """Enhanced queue manager with improved organization and maintainability"""

    def __init__(self, config: Optional[QueueConfig] = None):
        """Initialize queue manager components"""
        self.config = config or QueueConfig()
        self.coordinator = QueueCoordinator()
        self.stats = QueueStats()

        # Initialize managers
        self.state_manager = QueueStateManager(self.config.max_queue_size)
        self.metrics_manager = QueueMetricsManager()
        self.monitor = QueueMonitor(
            deadlock_threshold=self.config.deadlock_threshold,
            max_retries=self.config.max_retries,
            check_interval=self.config.check_interval
        )
        self.cleaner = QueueCleaner(
            cleanup_interval=self.config.cleanup_interval,
            max_history_age=self.config.max_history_age
        )
        
        # Initialize persistence if enabled
        self.persistence = (
            QueuePersistenceManager()
            if self.config.persistence_enabled
            else None
        )
        
        # Initialize processor
        self.processor = QueueProcessor(
            state_manager=self.state_manager,
            monitor=self.monitor,
            max_retries=self.config.max_retries,
            retry_delay=self.config.retry_delay,
            batch_size=self.config.batch_size,
            max_concurrent=self.config.max_concurrent
        )

        # Background tasks
        self._maintenance_task: Optional[asyncio.Task] = None
        self._stats_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize the queue manager components"""
        if self.coordinator.state != QueueState.UNINITIALIZED:
            logger.info("Queue manager already initialized")
            return

        try:
            await self.coordinator.set_state(QueueState.INITIALIZING)
            logger.info("Starting queue manager initialization...")
            
            # Load persisted state if available
            if self.persistence:
                await self._load_persisted_state()
            
            # Start monitoring with configured level
            self.monitor.strategy.level = self.config.monitoring_level
            await self.monitor.start(
                self.state_manager,
                self.metrics_manager
            )
            
            # Start cleanup task
            await self.cleaner.start(
                state_manager=self.state_manager,
                metrics_manager=self.metrics_manager
            )

            # Start background tasks
            self._start_background_tasks()

            await self.coordinator.set_state(QueueState.RUNNING)
            logger.info("Queue manager initialization completed")

        except Exception as e:
            await self.coordinator.set_state(QueueState.ERROR)
            logger.error(f"Failed to initialize queue manager: {e}")
            raise

    async def _load_persisted_state(self) -> None:
        """Load persisted queue state"""
        try:
            state = await self.persistence.load_queue_state()
            if state:
                await self.state_manager.restore_state(state)
                self.metrics_manager.restore_metrics(state.get("metrics", {}))
                logger.info("Loaded persisted queue state")
        except Exception as e:
            logger.error(f"Failed to load persisted state: {e}")

    def _start_background_tasks(self) -> None:
        """Start background maintenance tasks"""
        self._maintenance_task = asyncio.create_task(
            self._maintenance_loop()
        )
        self._stats_task = asyncio.create_task(
            self._stats_loop()
        )

    async def _maintenance_loop(self) -> None:
        """Background maintenance loop"""
        while self.coordinator.state not in (QueueState.STOPPED, QueueState.ERROR):
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                if self.coordinator.mode == QueueMode.MAINTENANCE:
                    continue

                # Perform maintenance tasks
                await self._perform_maintenance()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in maintenance loop: {e}")

    async def _stats_loop(self) -> None:
        """Background statistics loop"""
        while self.coordinator.state not in (QueueState.STOPPED, QueueState.ERROR):
            try:
                await asyncio.sleep(60)  # Every minute
                await self._update_stats()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in stats loop: {e}")

    async def _perform_maintenance(self) -> None:
        """Perform maintenance tasks"""
        try:
            # Switch to maintenance mode
            previous_mode = self.coordinator.mode
            await self.coordinator.set_mode(QueueMode.MAINTENANCE)

            # Perform maintenance tasks
            await self._cleanup_old_data()
            await self._optimize_queue()
            await self._persist_state()

            # Restore previous mode
            await self.coordinator.set_mode(previous_mode)

        except Exception as e:
            logger.error(f"Error during maintenance: {e}")

    async def _cleanup_old_data(self) -> None:
        """Clean up old data"""
        try:
            await self.cleaner.cleanup_old_data(
                self.state_manager,
                self.metrics_manager
            )
        except Exception as e:
            logger.error(f"Error cleaning up old data: {e}")

    async def _optimize_queue(self) -> None:
        """Optimize queue performance"""
        try:
            # Reorder queue based on priorities
            await self.state_manager.optimize_queue()
            
            # Update monitoring level based on queue size
            queue_size = len(await self.state_manager.get_all_items())
            if queue_size > self.config.max_queue_size * 0.8:
                self.monitor.strategy.level = MonitoringLevel.INTENSIVE
            elif queue_size < self.config.max_queue_size * 0.2:
                self.monitor.strategy.level = self.config.monitoring_level

        except Exception as e:
            logger.error(f"Error optimizing queue: {e}")

    async def _update_stats(self) -> None:
        """Update queue statistics"""
        try:
            self.stats.uptime = datetime.utcnow() - self.stats.start_time
            
            # Update peak values
            queue_size = len(await self.state_manager.get_all_items())
            self.stats.peak_queue_size = max(
                self.stats.peak_queue_size,
                queue_size
            )
            
            memory_usage = self.metrics_manager.peak_memory_usage
            self.stats.peak_memory_usage = max(
                self.stats.peak_memory_usage,
                memory_usage
            )

        except Exception as e:
            logger.error(f"Error updating stats: {e}")

    async def add_to_queue(
        self,
        url: str,
        message_id: int,
        channel_id: int,
        guild_id: int,
        author_id: int,
        priority: int = 0,
    ) -> bool:
        """Add a video to the processing queue"""
        if self.coordinator.state in (QueueState.STOPPED, QueueState.ERROR):
            raise QueueError("Queue manager is not running")

        # Wait if queue is paused
        await self.coordinator.wait_if_paused()

        try:
            item = QueueItem(
                url=url,
                message_id=message_id,
                channel_id=channel_id,
                guild_id=guild_id,
                author_id=author_id,
                added_at=datetime.utcnow(),
                priority=priority,
            )

            success = await self.state_manager.add_item(item)
            if success and self.persistence:
                await self._persist_state()

            return success

        except Exception as e:
            logger.error(f"Error adding to queue: {e}")
            raise QueueError(f"Failed to add to queue: {str(e)}")

    def get_queue_status(self, guild_id: int) -> Dict[str, Any]:
        """Get current queue status for a guild"""
        try:
            status = self.state_manager.get_guild_status(guild_id)
            metrics = self.metrics_manager.get_metrics()
            monitor_stats = self.monitor.get_monitoring_stats()
            
            return {
                **status,
                "metrics": metrics,
                "monitoring": monitor_stats,
                "state": self.coordinator.state.value,
                "mode": self.coordinator.mode.value,
                "stats": {
                    "uptime": self.stats.uptime.total_seconds(),
                    "peak_queue_size": self.stats.peak_queue_size,
                    "peak_memory_usage": self.stats.peak_memory_usage,
                    "total_processed": self.stats.total_processed,
                    "total_failed": self.stats.total_failed
                }
            }
        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            return self._get_default_status()

    async def pause(self) -> None:
        """Pause queue processing"""
        await self.coordinator.pause()
        logger.info("Queue processing paused")

    async def resume(self) -> None:
        """Resume queue processing"""
        await self.coordinator.resume()
        logger.info("Queue processing resumed")

    async def cleanup(self) -> None:
        """Clean up resources and stop queue processing"""
        try:
            await self.coordinator.set_state(QueueState.STOPPING)
            logger.info("Starting queue manager cleanup...")
            
            # Cancel background tasks
            if self._maintenance_task:
                self._maintenance_task.cancel()
            if self._stats_task:
                self._stats_task.cancel()
            
            # Stop processor
            await self.processor.stop_processing()
            
            # Stop monitoring and cleanup
            await self.monitor.stop()
            await self.cleaner.stop()

            # Final state persistence
            if self.persistence:
                await self._persist_state()

            # Clear state
            await self.state_manager.clear_state()

            await self.coordinator.set_state(QueueState.STOPPED)
            logger.info("Queue manager cleanup completed")

        except Exception as e:
            await self.coordinator.set_state(QueueState.ERROR)
            logger.error(f"Error during cleanup: {e}")
            raise CleanupError(f"Failed to clean up queue manager: {str(e)}")

    async def force_stop(self) -> None:
        """Force stop all queue operations immediately"""
        await self.coordinator.set_state(QueueState.STOPPING)
        logger.info("Force stopping queue manager...")
        
        # Cancel background tasks
        if self._maintenance_task:
            self._maintenance_task.cancel()
        if self._stats_task:
            self._stats_task.cancel()
        
        # Force stop all components
        await self.processor.stop_processing()
        await self.monitor.stop()
        await self.cleaner.stop()
        
        # Clear state
        await self.state_manager.clear_state()
        
        await self.coordinator.set_state(QueueState.STOPPED)
        logger.info("Queue manager force stopped")

    async def _persist_state(self) -> None:
        """Persist current state to storage"""
        if not self.persistence:
            return
            
        try:
            state = await self.state_manager.get_state_for_persistence()
            state["metrics"] = self.metrics_manager.get_metrics()
            state["stats"] = {
                "uptime": self.stats.uptime.total_seconds(),
                "peak_queue_size": self.stats.peak_queue_size,
                "peak_memory_usage": self.stats.peak_memory_usage,
                "total_processed": self.stats.total_processed,
                "total_failed": self.stats.total_failed
            }
            await self.persistence.persist_queue_state(state)
        except Exception as e:
            logger.error(f"Failed to persist state: {e}")

    def _get_default_status(self) -> Dict[str, Any]:
        """Get default status when error occurs"""
        return {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "metrics": {
                "total_processed": 0,
                "total_failed": 0,
                "success_rate": 0.0,
                "avg_processing_time": 0.0,
                "peak_memory_usage": 0.0,
                "last_cleanup": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "errors_by_type": {},
                "compression_failures": 0,
                "hardware_accel_failures": 0,
                "last_activity": 0,
            },
            "state": QueueState.ERROR.value,
            "mode": QueueMode.NORMAL.value,
            "stats": {
                "uptime": 0,
                "peak_queue_size": 0,
                "peak_memory_usage": 0,
                "total_processed": 0,
                "total_failed": 0
            }
        }
