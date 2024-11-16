"""Core VideoProcessor class that manages video processing operations"""

import logging
import asyncio
from enum import Enum
from typing import Optional, Tuple, Dict, Any
from datetime import datetime
import discord
from discord.ext import commands

from .message_handler import MessageHandler
from .queue_handler import QueueHandler
from .progress_tracker import ProgressTracker
from .status_display import StatusDisplay
from .cleanup_manager import CleanupManager
from .reactions import REACTIONS

logger = logging.getLogger("VideoArchiver")

class ProcessorState(Enum):
    """Possible states of the video processor"""
    INITIALIZING = "initializing"
    READY = "ready"
    PROCESSING = "processing"
    PAUSED = "paused"
    ERROR = "error"
    SHUTDOWN = "shutdown"

class OperationType(Enum):
    """Types of processor operations"""
    MESSAGE_PROCESSING = "message_processing"
    VIDEO_PROCESSING = "video_processing"
    QUEUE_MANAGEMENT = "queue_management"
    CLEANUP = "cleanup"

class OperationTracker:
    """Tracks processor operations"""

    def __init__(self):
        self.operations: Dict[str, Dict[str, Any]] = {}
        self.operation_history: List[Dict[str, Any]] = []
        self.error_count = 0
        self.success_count = 0

    def start_operation(
        self,
        op_type: OperationType,
        details: Dict[str, Any]
    ) -> str:
        """Start tracking an operation"""
        op_id = f"{op_type.value}_{datetime.utcnow().timestamp()}"
        self.operations[op_id] = {
            "type": op_type.value,
            "start_time": datetime.utcnow(),
            "status": "running",
            "details": details
        }
        return op_id

    def end_operation(
        self,
        op_id: str,
        success: bool,
        error: Optional[str] = None
    ) -> None:
        """End tracking an operation"""
        if op_id in self.operations:
            self.operations[op_id].update({
                "end_time": datetime.utcnow(),
                "status": "success" if success else "error",
                "error": error
            })
            # Move to history
            self.operation_history.append(self.operations.pop(op_id))
            # Update counts
            if success:
                self.success_count += 1
            else:
                self.error_count += 1

    def get_active_operations(self) -> Dict[str, Dict[str, Any]]:
        """Get currently active operations"""
        return self.operations.copy()

    def get_operation_stats(self) -> Dict[str, Any]:
        """Get operation statistics"""
        return {
            "total_operations": len(self.operation_history) + len(self.operations),
            "active_operations": len(self.operations),
            "success_count": self.success_count,
            "error_count": self.error_count,
            "success_rate": (
                self.success_count / (self.success_count + self.error_count)
                if (self.success_count + self.error_count) > 0
                else 0
            )
        }

class HealthMonitor:
    """Monitors processor health"""

    def __init__(self, processor: 'VideoProcessor'):
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

    async def _monitor_health(self) -> None:
        """Monitor processor health"""
        while True:
            try:
                self.last_check = datetime.utcnow()
                
                # Check component health
                self.health_status.update({
                    "queue_handler": self.processor.queue_handler.is_healthy(),
                    "message_handler": self.processor.message_handler.is_healthy(),
                    "progress_tracker": self.processor.progress_tracker.is_healthy()
                })

                # Check operation health
                op_stats = self.processor.operation_tracker.get_operation_stats()
                self.health_status["operations"] = (
                    op_stats["success_rate"] >= 0.9  # 90% success rate threshold
                )

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(30)  # Shorter interval on error

    def is_healthy(self) -> bool:
        """Check if processor is healthy"""
        return all(self.health_status.values())

class VideoProcessor:
    """Handles video processing operations"""

    def __init__(
        self,
        bot,
        config_manager,
        components,
        queue_manager=None,
        ffmpeg_mgr=None,
        db=None
    ):
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

        # Initialize handlers
        self.queue_handler = QueueHandler(bot, config_manager, components)
        self.message_handler = MessageHandler(bot, config_manager, queue_manager)
        self.progress_tracker = ProgressTracker()
        self.cleanup_manager = CleanupManager(self.queue_handler, ffmpeg_mgr)

        # Pass db to queue handler if it exists
        if self.db:
            self.queue_handler.db = self.db

        # Store queue task reference
        self._queue_task = None
        
        # Mark as ready
        self.state = ProcessorState.READY
        logger.info("VideoProcessor initialized successfully")

    async def start(self) -> None:
        """Start processor operations"""
        await self.health_monitor.start_monitoring()

    async def process_video(self, item) -> Tuple[bool, Optional[str]]:
        """Process a video from the queue"""
        op_id = self.operation_tracker.start_operation(
            OperationType.VIDEO_PROCESSING,
            {"item": str(item)}
        )
        
        try:
            self.state = ProcessorState.PROCESSING
            result = await self.queue_handler.process_video(item)
            success = result[0]
            error = None if success else result[1]
            self.operation_tracker.end_operation(op_id, success, error)
            return result
        except Exception as e:
            self.operation_tracker.end_operation(op_id, False, str(e))
            raise
        finally:
            self.state = ProcessorState.READY

    async def process_message(self, message: discord.Message) -> None:
        """Process a message for video content"""
        op_id = self.operation_tracker.start_operation(
            OperationType.MESSAGE_PROCESSING,
            {"message_id": message.id}
        )
        
        try:
            await self.message_handler.process_message(message)
            self.operation_tracker.end_operation(op_id, True)
        except Exception as e:
            self.operation_tracker.end_operation(op_id, False, str(e))
            raise

    async def cleanup(self) -> None:
        """Clean up resources and stop processing"""
        op_id = self.operation_tracker.start_operation(
            OperationType.CLEANUP,
            {"type": "normal"}
        )
        
        try:
            self.state = ProcessorState.SHUTDOWN
            await self.health_monitor.stop_monitoring()
            await self.cleanup_manager.cleanup()
            self.operation_tracker.end_operation(op_id, True)
        except Exception as e:
            self.operation_tracker.end_operation(op_id, False, str(e))
            logger.error(f"Error during cleanup: {e}", exc_info=True)
            raise

    async def force_cleanup(self) -> None:
        """Force cleanup of resources"""
        op_id = self.operation_tracker.start_operation(
            OperationType.CLEANUP,
            {"type": "force"}
        )
        
        try:
            self.state = ProcessorState.SHUTDOWN
            await self.health_monitor.stop_monitoring()
            await self.cleanup_manager.force_cleanup()
            self.operation_tracker.end_operation(op_id, True)
        except Exception as e:
            self.operation_tracker.end_operation(op_id, False, str(e))
            raise

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
                queue_status,
                active_ops
            )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error showing queue details: {e}", exc_info=True)
            await ctx.send(f"Error getting queue details: {str(e)}")

    def set_queue_task(self, task: asyncio.Task) -> None:
        """Set the queue processing task"""
        self._queue_task = task
        self.cleanup_manager.set_queue_task(task)

    def get_status(self) -> Dict[str, Any]:
        """Get processor status"""
        return {
            "state": self.state.value,
            "health": self.health_monitor.is_healthy(),
            "operations": self.operation_tracker.get_operation_stats(),
            "active_operations": self.operation_tracker.get_active_operations(),
            "last_health_check": (
                self.health_monitor.last_check.isoformat()
                if self.health_monitor.last_check
                else None
            ),
            "health_status": self.health_monitor.health_status
        }
