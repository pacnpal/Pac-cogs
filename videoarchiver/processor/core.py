"""Core VideoProcessor class that manages video processing operations"""

import asyncio
import logging
from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import discord  # type: ignore
from discord.ext import commands  # type: ignore

from ..core.types import (
    IComponent,
    IConfigManager,
    IQueueManager,
    ProcessorState,
    ComponentStatus,
)
from ..processor.cleanup_manager import CleanupManager, CleanupStrategy
from ..processor.constants import REACTIONS
from ..processor.message_handler import MessageHandler
from ..processor.queue_handler import QueueHandler
from ..processor.status_display import StatusDisplay
from ..utils import progress_tracker
from ..utils.exceptions import ProcessorError

logger = logging.getLogger("VideoArchiver")


class OperationTracker:
    """Tracks processor operations"""

    MAX_HISTORY: ClassVar[int] = 1000  # Maximum number of operations to track

    def __init__(self) -> None:
        self.operations: Dict[str, Dict[str, Any]] = {}
        self.operation_history: List[Dict[str, Any]] = []
        self.error_count = 0
        self.success_count = 0

    def start_operation(self, op_type: str, details: Dict[str, Any]) -> str:
        """Start tracking an operation"""
        op_id = f"{op_type}_{datetime.utcnow().timestamp()}"
        self.operations[op_id] = {
            "type": op_type,
            "start_time": datetime.utcnow(),
            "end_time": None,
            "status": "running",
            "details": details,
            "error": None,
        }
        return op_id

    def end_operation(
        self, op_id: str, success: bool, error: Optional[str] = None
    ) -> None:
        """End tracking an operation"""
        if op_id in self.operations:
            self.operations[op_id].update({
                "end_time": datetime.utcnow(),
                "status": "success" if success else "error",
                "error": error,
            })
            # Move to history
            self.operation_history.append(self.operations.pop(op_id))
            # Update counts
            if success:
                self.success_count += 1
            else:
                self.error_count += 1

            # Cleanup old history if needed
            if len(self.operation_history) > self.MAX_HISTORY:
                self.operation_history = self.operation_history[-self.MAX_HISTORY:]

    def get_active_operations(self) -> Dict[str, Dict[str, Any]]:
        """Get currently active operations"""
        return self.operations.copy()

    def get_operation_stats(self) -> Dict[str, Any]:
        """Get operation statistics"""
        total = self.success_count + self.error_count
        return {
            "total_operations": len(self.operation_history) + len(self.operations),
            "active_operations": len(self.operations),
            "success_count": self.success_count,
            "error_count": self.error_count,
            "success_rate": self.success_count / total if total > 0 else 0.0,
        }


class HealthMonitor:
    """Monitors processor health"""

    HEALTH_CHECK_INTERVAL: ClassVar[int] = 60  # Seconds between health checks
    ERROR_CHECK_INTERVAL: ClassVar[int] = 30  # Seconds between checks after error
    SUCCESS_RATE_THRESHOLD: ClassVar[float] = 0.9  # 90% success rate threshold

    def __init__(self, processor: "VideoProcessor") -> None:
        self.processor = processor
        self.last_check: Optional[datetime] = None
        self.health_status: Dict[str, bool] = {}
        self._monitor_task: Optional[asyncio.Task] = None

    async def start_monitoring(self) -> None:
        """Start health monitoring"""
        self._monitor_task = asyncio.create_task(self._monitor_health())

    async def stop_monitoring(self) -> None:
        """Stop health monitoring"""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error stopping health monitor: {e}")

    async def _monitor_health(self) -> None:
        """Monitor processor health"""
        while True:
            try:
                self.last_check = datetime.utcnow()

                # Check component health
                self.health_status.update({
                    "queue_handler": self.processor.queue_handler.is_healthy(),
                    "message_handler": self.processor.message_handler.is_healthy(),
                    "progress_tracker": progress_tracker.is_healthy(),
                })

                # Check operation health
                op_stats = self.processor.operation_tracker.get_operation_stats()
                self.health_status["operations"] = (
                    op_stats["success_rate"] >= self.SUCCESS_RATE_THRESHOLD
                )

                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Health monitoring error: {e}", exc_info=True)
                await asyncio.sleep(self.ERROR_CHECK_INTERVAL)

    def is_healthy(self) -> bool:
        """Check if processor is healthy"""
        return all(self.health_status.values())


class VideoProcessor(IComponent):
    """Handles video processing operations"""

    def __init__(
        self,
        bot: commands.Bot,
        config_manager: IConfigManager,
        components: Dict[int, Dict[str, Any]],
        queue_manager: Optional[IQueueManager] = None,
        ffmpeg_mgr: Optional[Any] = None,
        db: Optional[Any] = None,
    ) -> None:
        self.bot = bot
        self.config = config_manager
        self.components = components
        self.ffmpeg_mgr = ffmpeg_mgr
        self.db = db
        self.queue_manager = queue_manager

        # Initialize state
        self._state = ProcessorState.INITIALIZING
        self.operation_tracker = OperationTracker()
        self.health_monitor = HealthMonitor(self)

        try:
            # Initialize handlers
            self.queue_handler = QueueHandler(bot, config_manager, components)
            self.message_handler = MessageHandler(bot, config_manager, queue_manager)
            self.cleanup_manager = CleanupManager(
                self.queue_handler, ffmpeg_mgr, CleanupStrategy.NORMAL
            )

            # Pass db to queue handler if it exists
            if self.db:
                self.queue_handler.db = self.db

            # Store queue task reference
            self._queue_task: Optional[asyncio.Task] = None

            # Mark as ready
            self._state = ProcessorState.READY
            logger.info("VideoProcessor initialized successfully")

        except Exception as e:
            self._state = ProcessorState.ERROR
            logger.error(f"Error initializing VideoProcessor: {e}", exc_info=True)
            raise ProcessorError(f"Failed to initialize processor: {str(e)}")

    @property
    def state(self) -> ProcessorState:
        """Get processor state"""
        return self._state

    async def initialize(self) -> None:
        """Initialize the processor"""
        try:
            await self.health_monitor.start_monitoring()
            logger.info("VideoProcessor started successfully")
        except Exception as e:
            error = f"Failed to start processor: {str(e)}"
            logger.error(error, exc_info=True)
            raise ProcessorError(error)

    async def process_video(self, item: Any) -> Tuple[bool, Optional[str]]:
        """Process a video from the queue"""
        op_id = self.operation_tracker.start_operation(
            "video_processing", {"item": str(item)}
        )

        try:
            self._state = ProcessorState.PROCESSING
            result = await self.queue_handler.process_video(item)
            success = result[0]
            error = None if success else result[1]
            self.operation_tracker.end_operation(op_id, success, error)
            return result
        except Exception as e:
            error = f"Video processing failed: {str(e)}"
            self.operation_tracker.end_operation(op_id, False, error)
            logger.error(error, exc_info=True)
            raise ProcessorError(error)
        finally:
            self._state = ProcessorState.READY

    async def process_message(self, message: discord.Message) -> None:
        """Process a message for video content"""
        op_id = self.operation_tracker.start_operation(
            "message_processing", {"message_id": message.id}
        )

        try:
            await self.message_handler.process_message(message)
            self.operation_tracker.end_operation(op_id, True)
        except Exception as e:
            error = f"Message processing failed: {str(e)}"
            self.operation_tracker.end_operation(op_id, False, error)
            logger.error(error, exc_info=True)
            raise ProcessorError(error)

    async def cleanup(self) -> None:
        """Clean up resources and stop processing"""
        op_id = self.operation_tracker.start_operation(
            "cleanup", {"type": "normal"}
        )

        try:
            self._state = ProcessorState.SHUTDOWN
            await self.health_monitor.stop_monitoring()
            await self.cleanup_manager.cleanup()
            self.operation_tracker.end_operation(op_id, True)
        except Exception as e:
            error = f"Cleanup failed: {str(e)}"
            self.operation_tracker.end_operation(op_id, False, error)
            logger.error(error, exc_info=True)
            raise ProcessorError(error)

    async def force_cleanup(self) -> None:
        """Force cleanup of resources"""
        op_id = self.operation_tracker.start_operation(
            "cleanup", {"type": "force"}
        )

        try:
            self._state = ProcessorState.SHUTDOWN
            await self.health_monitor.stop_monitoring()
            await self.cleanup_manager.force_cleanup()
            self.operation_tracker.end_operation(op_id, True)
        except Exception as e:
            error = f"Force cleanup failed: {str(e)}"
            self.operation_tracker.end_operation(op_id, False, error)
            logger.error(error, exc_info=True)
            raise ProcessorError(error)

    async def show_queue_details(self, ctx: commands.Context) -> None:
        """Display detailed queue status"""
        try:
            if not self.queue_manager:
                await ctx.send("Queue manager is not initialized.")
                return

            # Get queue status
            queue_status = self.queue_manager.get_queue_status(ctx.guild.id)

            # Get active operations
            active_ops = self.operation_tracker.get_active_operations()

            # Create and send status embed
            embed = await StatusDisplay.create_queue_status_embed(
                queue_status, active_ops
            )
            await ctx.send(embed=embed)

        except Exception as e:
            error = f"Failed to show queue details: {str(e)}"
            logger.error(error, exc_info=True)
            await ctx.send(f"Error getting queue details: {str(e)}")

    def set_queue_task(self, task: asyncio.Task) -> None:
        """Set the queue processing task"""
        self._queue_task = task
        self.cleanup_manager.set_queue_task(task)

    def get_status(self) -> ComponentStatus:
        """Get processor status"""
        return ComponentStatus(
            state=self._state.name,
            health=self.health_monitor.is_healthy(),
            last_check=(
                self.health_monitor.last_check.isoformat()
                if self.health_monitor.last_check
                else None
            ),
            details={
                "operations": self.operation_tracker.get_operation_stats(),
                "active_operations": self.operation_tracker.get_active_operations(),
                "health_status": self.health_monitor.health_status,
            }
        )
