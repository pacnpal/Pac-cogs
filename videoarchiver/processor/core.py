"""Core VideoProcessor class that manages video processing operations"""

import asyncio
import logging
from datetime import datetime, timedelta
from enum import auto, Enum
from typing import Any, ClassVar, Dict, List, Optional, Tuple, TypedDict

import discord  # type: ignore
from discord.ext import commands  # type: ignore

from ..config_manager import ConfigManager
from ..database.video_archive_db import VideoArchiveDB
from ..ffmpeg.ffmpeg_manager import FFmpegManager
from ..processor.cleanup_manager import CleanupManager, CleanupStrategy
from ..processor.constants import REACTIONS

from ..processor.message_handler import MessageHandler
from ..processor.queue_handler import QueueHandler
from ..processor.status_display import StatusDisplay
from ..queue.manager import EnhancedVideoQueueManager
from ..utils import progress_tracker
from ..utils.exceptions import ProcessorError

logger = logging.getLogger("VideoArchiver")


class ProcessorState(Enum):
    """Possible states of the video processor"""

    INITIALIZING = auto()
    READY = auto()
    PROCESSING = auto()
    PAUSED = auto()
    ERROR = auto()
    SHUTDOWN = auto()


class OperationType(Enum):
    """Types of processor operations"""

    MESSAGE_PROCESSING = auto()
    VIDEO_PROCESSING = auto()
    QUEUE_MANAGEMENT = auto()
    CLEANUP = auto()


class OperationDetails(TypedDict):
    """Type definition for operation details"""

    type: str
    start_time: datetime
    end_time: Optional[datetime]
    status: str
    details: Dict[str, Any]
    error: Optional[str]


class OperationStats(TypedDict):
    """Type definition for operation statistics"""

    total_operations: int
    active_operations: int
    success_count: int
    error_count: int
    success_rate: float


class ProcessorStatus(TypedDict):
    """Type definition for processor status"""

    state: str
    health: bool
    operations: OperationStats
    active_operations: Dict[str, OperationDetails]
    last_health_check: Optional[str]
    health_status: Dict[str, bool]


class OperationTracker:
    """Tracks processor operations"""

    MAX_HISTORY: ClassVar[int] = 1000  # Maximum number of operations to track

    def __init__(self) -> None:
        self.operations: Dict[str, OperationDetails] = {}
        self.operation_history: List[OperationDetails] = []
        self.error_count = 0
        self.success_count = 0

    def start_operation(self, op_type: OperationType, details: Dict[str, Any]) -> str:
        """
        Start tracking an operation.

        Args:
            op_type: Type of operation
            details: Operation details

        Returns:
            Operation ID string
        """
        op_id = f"{op_type.value}_{datetime.utcnow().timestamp()}"
        self.operations[op_id] = OperationDetails(
            type=op_type.value,
            start_time=datetime.utcnow(),
            end_time=None,
            status="running",
            details=details,
            error=None,
        )
        return op_id

    def end_operation(
        self, op_id: str, success: bool, error: Optional[str] = None
    ) -> None:
        """
        End tracking an operation.

        Args:
            op_id: Operation ID
            success: Whether operation succeeded
            error: Optional error message
        """
        if op_id in self.operations:
            self.operations[op_id].update(
                {
                    "end_time": datetime.utcnow(),
                    "status": "success" if success else "error",
                    "error": error,
                }
            )
            # Move to history
            self.operation_history.append(self.operations.pop(op_id))
            # Update counts
            if success:
                self.success_count += 1
            else:
                self.error_count += 1

            # Cleanup old history if needed
            if len(self.operation_history) > self.MAX_HISTORY:
                self.operation_history = self.operation_history[-self.MAX_HISTORY :]

    def get_active_operations(self) -> Dict[str, OperationDetails]:
        """
        Get currently active operations.

        Returns:
            Dictionary of active operations
        """
        return self.operations.copy()

    def get_operation_stats(self) -> OperationStats:
        """
        Get operation statistics.

        Returns:
            Dictionary containing operation statistics
        """
        total = self.success_count + self.error_count
        return OperationStats(
            total_operations=len(self.operation_history) + len(self.operations),
            active_operations=len(self.operations),
            success_count=self.success_count,
            error_count=self.error_count,
            success_rate=self.success_count / total if total > 0 else 0.0,
        )


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
                self.health_status.update(
                    {
                        "queue_handler": self.processor.queue_handler.is_healthy(),
                        "message_handler": self.processor.message_handler.is_healthy(),
                        "progress_tracker": progress_tracker.is_healthy(),
                    }
                )

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
        """
        Check if processor is healthy.

        Returns:
            True if all components are healthy, False otherwise
        """
        return all(self.health_status.values())


class VideoProcessor:
    """Handles video processing operations"""

    def __init__(
        self,
        bot: commands.Bot,
        config_manager: ConfigManager,
        components: Dict[int, Dict[str, Any]],
        queue_manager: Optional[EnhancedVideoQueueManager] = None,
        ffmpeg_mgr: Optional[FFmpegManager] = None,
        db: Optional[VideoArchiveDB] = None,
    ) -> None:
        self.bot = bot
        self.config = config_manager
        self.components = components
        self.ffmpeg_mgr = ffmpeg_mgr
        self.db = db
        self.queue_manager = queue_manager

        # Initialize state
        self.state = ProcessorState.INITIALIZING
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
            self.state = ProcessorState.READY
            logger.info("VideoProcessor initialized successfully")

        except Exception as e:
            self.state = ProcessorState.ERROR
            logger.error(f"Error initializing VideoProcessor: {e}", exc_info=True)
            raise ProcessorError(f"Failed to initialize processor: {str(e)}")

    async def start(self) -> None:
        """
        Start processor operations.

        Raises:
            ProcessorError: If startup fails
        """
        try:
            await self.health_monitor.start_monitoring()
            logger.info("VideoProcessor started successfully")
        except Exception as e:
            error = f"Failed to start processor: {str(e)}"
            logger.error(error, exc_info=True)
            raise ProcessorError(error)

    async def process_video(self, item: Any) -> Tuple[bool, Optional[str]]:
        """
        Process a video from the queue.

        Args:
            item: Queue item to process

        Returns:
            Tuple of (success, error_message)

        Raises:
            ProcessorError: If processing fails
        """
        op_id = self.operation_tracker.start_operation(
            OperationType.VIDEO_PROCESSING, {"item": str(item)}
        )

        try:
            self.state = ProcessorState.PROCESSING
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
            self.state = ProcessorState.READY

    async def process_message(self, message: discord.Message) -> None:
        """
        Process a message for video content.

        Args:
            message: Discord message to process

        Raises:
            ProcessorError: If processing fails
        """
        op_id = self.operation_tracker.start_operation(
            OperationType.MESSAGE_PROCESSING, {"message_id": message.id}
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
        """
        Clean up resources and stop processing.

        Raises:
            ProcessorError: If cleanup fails
        """
        op_id = self.operation_tracker.start_operation(
            OperationType.CLEANUP, {"type": "normal"}
        )

        try:
            self.state = ProcessorState.SHUTDOWN
            await self.health_monitor.stop_monitoring()
            await self.cleanup_manager.cleanup()
            self.operation_tracker.end_operation(op_id, True)
        except Exception as e:
            error = f"Cleanup failed: {str(e)}"
            self.operation_tracker.end_operation(op_id, False, error)
            logger.error(error, exc_info=True)
            raise ProcessorError(error)

    async def force_cleanup(self) -> None:
        """
        Force cleanup of resources.

        Raises:
            ProcessorError: If force cleanup fails
        """
        op_id = self.operation_tracker.start_operation(
            OperationType.CLEANUP, {"type": "force"}
        )

        try:
            self.state = ProcessorState.SHUTDOWN
            await self.health_monitor.stop_monitoring()
            await self.cleanup_manager.force_cleanup()
            self.operation_tracker.end_operation(op_id, True)
        except Exception as e:
            error = f"Force cleanup failed: {str(e)}"
            self.operation_tracker.end_operation(op_id, False, error)
            logger.error(error, exc_info=True)
            raise ProcessorError(error)

    async def show_queue_details(self, ctx: commands.Context) -> None:
        """
        Display detailed queue status.

        Args:
            ctx: Command context
        """
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
        """
        Set the queue processing task.

        Args:
            task: Queue processing task
        """
        self._queue_task = task
        self.cleanup_manager.set_queue_task(task)

    def get_status(self) -> ProcessorStatus:
        """
        Get processor status.

        Returns:
            Dictionary containing processor status information
        """
        return ProcessorStatus(
            state=self.state.value,
            health=self.health_monitor.is_healthy(),
            operations=self.operation_tracker.get_operation_stats(),
            active_operations=self.operation_tracker.get_active_operations(),
            last_health_check=(
                self.health_monitor.last_check.isoformat()
                if self.health_monitor.last_check
                else None
            ),
            health_status=self.health_monitor.health_status,
        )
