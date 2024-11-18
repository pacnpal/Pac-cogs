"""Module for managing cleanup operations in the video processor"""

import logging
import asyncio
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import (
    Optional,
    Dict,
    Any,
    List,
    Set,
    TypedDict,
    ClassVar,
    Callable,
    Awaitable,
    Tuple,
    TYPE_CHECKING,
)
from datetime import datetime, timedelta

if TYPE_CHECKING:
    from .queue_handler import QueueHandler

    # try:
    # Try relative imports first
    from ..ffmpeg.ffmpeg_manager import FFmpegManager
    from ..utils.exceptions import CleanupError
# except ImportError:
# Fall back to absolute imports if relative imports fail
#   from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager
#  from videoarchiver.utils.exceptions import CleanupError

logger = logging.getLogger("VideoArchiver")


class CleanupStage(Enum):
    """Cleanup stages"""

    QUEUE = auto()
    FFMPEG = auto()
    TASKS = auto()
    RESOURCES = auto()


class CleanupStrategy(Enum):
    """Cleanup strategies"""

    NORMAL = auto()
    FORCE = auto()
    GRACEFUL = auto()


class CleanupStats(TypedDict):
    """Type definition for cleanup statistics"""

    total_cleanups: int
    active_cleanups: int
    success_rate: float
    average_duration: float
    stage_success_rates: Dict[str, float]


@dataclass
class CleanupResult:
    """Result of a cleanup operation"""

    success: bool
    stage: CleanupStage
    error: Optional[str] = None
    duration: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CleanupOperation:
    """Represents a cleanup operation"""

    stage: CleanupStage
    func: Callable[[], Awaitable[None]]
    force_func: Optional[Callable[[], Awaitable[None]]] = None
    timeout: float = 30.0  # Default timeout in seconds


class CleanupTracker:
    """Tracks cleanup operations"""

    MAX_HISTORY: ClassVar[int] = 1000  # Maximum number of cleanup operations to track

    def __init__(self) -> None:
        self.cleanup_history: List[Dict[str, Any]] = []
        self.active_cleanups: Set[str] = set()
        self.start_times: Dict[str, datetime] = {}
        self.stage_results: Dict[str, List[CleanupResult]] = {}

    def start_cleanup(self, cleanup_id: str) -> None:
        """
        Start tracking a cleanup operation.

        Args:
            cleanup_id: Unique identifier for the cleanup operation
        """
        self.active_cleanups.add(cleanup_id)
        self.start_times[cleanup_id] = datetime.utcnow()
        self.stage_results[cleanup_id] = []

        # Cleanup old history if needed
        if len(self.cleanup_history) >= self.MAX_HISTORY:
            self.cleanup_history = self.cleanup_history[-self.MAX_HISTORY :]

    def record_stage_result(self, cleanup_id: str, result: CleanupResult) -> None:
        """
        Record result of a cleanup stage.

        Args:
            cleanup_id: Cleanup operation identifier
            result: Result of the cleanup stage
        """
        if cleanup_id in self.stage_results:
            self.stage_results[cleanup_id].append(result)

    def end_cleanup(self, cleanup_id: str) -> None:
        """
        End tracking a cleanup operation.

        Args:
            cleanup_id: Cleanup operation identifier
        """
        if cleanup_id in self.active_cleanups:
            end_time = datetime.utcnow()
            self.cleanup_history.append(
                {
                    "id": cleanup_id,
                    "start_time": self.start_times[cleanup_id],
                    "end_time": end_time,
                    "duration": (
                        end_time - self.start_times[cleanup_id]
                    ).total_seconds(),
                    "results": self.stage_results[cleanup_id],
                }
            )
            self.active_cleanups.remove(cleanup_id)
            self.start_times.pop(cleanup_id)
            self.stage_results.pop(cleanup_id)

    def get_cleanup_stats(self) -> CleanupStats:
        """
        Get cleanup statistics.

        Returns:
            Dictionary containing cleanup statistics
        """
        return CleanupStats(
            total_cleanups=len(self.cleanup_history),
            active_cleanups=len(self.active_cleanups),
            success_rate=self._calculate_success_rate(),
            average_duration=self._calculate_average_duration(),
            stage_success_rates=self._calculate_stage_success_rates(),
        )

    def _calculate_success_rate(self) -> float:
        """Calculate overall cleanup success rate"""
        if not self.cleanup_history:
            return 1.0
        successful = sum(
            1
            for cleanup in self.cleanup_history
            if all(result.success for result in cleanup["results"])
        )
        return successful / len(self.cleanup_history)

    def _calculate_average_duration(self) -> float:
        """Calculate average cleanup duration"""
        if not self.cleanup_history:
            return 0.0
        total_duration = sum(cleanup["duration"] for cleanup in self.cleanup_history)
        return total_duration / len(self.cleanup_history)

    def _calculate_stage_success_rates(self) -> Dict[str, float]:
        """Calculate success rates by stage"""
        stage_attempts: Dict[str, int] = {}
        stage_successes: Dict[str, int] = {}

        for cleanup in self.cleanup_history:
            for result in cleanup["results"]:
                stage = result.stage.value
                stage_attempts[stage] = stage_attempts.get(stage, 0) + 1
                if result.success:
                    stage_successes[stage] = stage_successes.get(stage, 0) + 1

        return {
            stage: stage_successes.get(stage, 0) / attempts
            for stage, attempts in stage_attempts.items()
        }


class CleanupManager:
    """Manages cleanup operations for the video processor"""

    CLEANUP_TIMEOUT: ClassVar[int] = 60  # Default timeout for entire cleanup operation

    def __init__(
        self,
        queue_handler: "QueueHandler",
        ffmpeg_mgr: Optional[FFmpegManager] = None,
        strategy: CleanupStrategy = CleanupStrategy.NORMAL,
    ) -> None:
        self.queue_handler = queue_handler
        self.ffmpeg_mgr = ffmpeg_mgr
        self.strategy = strategy
        self._queue_task: Optional[asyncio.Task] = None
        self.tracker = CleanupTracker()

        # Define cleanup operations
        self.cleanup_operations: List[CleanupOperation] = [
            CleanupOperation(
                stage=CleanupStage.QUEUE,
                func=self._cleanup_queue,
                force_func=self._force_cleanup_queue,
                timeout=30.0,
            ),
            CleanupOperation(
                stage=CleanupStage.FFMPEG,
                func=self._cleanup_ffmpeg,
                force_func=self._force_cleanup_ffmpeg,
                timeout=15.0,
            ),
            CleanupOperation(
                stage=CleanupStage.TASKS,
                func=self._cleanup_tasks,
                force_func=self._force_cleanup_tasks,
                timeout=15.0,
            ),
        ]

    async def cleanup(self) -> None:
        """
        Perform normal cleanup of resources.

        Raises:
            CleanupError: If cleanup fails
        """
        cleanup_id = f"cleanup_{datetime.utcnow().timestamp()}"
        self.tracker.start_cleanup(cleanup_id)

        try:
            logger.info("Starting normal cleanup...")

            # Clean up in stages
            for operation in self.cleanup_operations:
                try:
                    start_time = datetime.utcnow()
                    await asyncio.wait_for(operation.func(), timeout=operation.timeout)
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    self.tracker.record_stage_result(
                        cleanup_id,
                        CleanupResult(True, operation.stage, duration=duration),
                    )
                except asyncio.TimeoutError:
                    error = f"Cleanup stage {operation.stage.value} timed out"
                    logger.error(error)
                    self.tracker.record_stage_result(
                        cleanup_id, CleanupResult(False, operation.stage, error)
                    )
                    if self.strategy != CleanupStrategy.GRACEFUL:
                        raise CleanupError(error)
                except Exception as e:
                    error = f"Error in {operation.stage.value} cleanup: {e}"
                    logger.error(error)
                    self.tracker.record_stage_result(
                        cleanup_id, CleanupResult(False, operation.stage, str(e))
                    )
                    if self.strategy != CleanupStrategy.GRACEFUL:
                        raise CleanupError(error)

            logger.info("Normal cleanup completed successfully")

        except CleanupError:
            raise
        except Exception as e:
            error = f"Unexpected error during cleanup: {str(e)}"
            logger.error(error, exc_info=True)
            raise CleanupError(error)
        finally:
            self.tracker.end_cleanup(cleanup_id)

    async def force_cleanup(self) -> None:
        """Force cleanup of resources when normal cleanup fails"""
        cleanup_id = f"force_cleanup_{datetime.utcnow().timestamp()}"
        self.tracker.start_cleanup(cleanup_id)

        try:
            logger.info("Starting force cleanup...")

            # Force cleanup in stages
            for operation in self.cleanup_operations:
                if not operation.force_func:
                    continue

                try:
                    start_time = datetime.utcnow()
                    await asyncio.wait_for(
                        operation.force_func(), timeout=operation.timeout
                    )
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    self.tracker.record_stage_result(
                        cleanup_id,
                        CleanupResult(True, operation.stage, duration=duration),
                    )
                except Exception as e:
                    logger.error(f"Error in force {operation.stage.value} cleanup: {e}")
                    self.tracker.record_stage_result(
                        cleanup_id, CleanupResult(False, operation.stage, str(e))
                    )

            logger.info("Force cleanup completed")

        except Exception as e:
            logger.error(f"Error during force cleanup: {str(e)}", exc_info=True)
        finally:
            self.tracker.end_cleanup(cleanup_id)

    async def _cleanup_queue(self) -> None:
        """Clean up queue handler"""
        if not self.queue_handler:
            raise CleanupError("Queue handler not initialized")
        await self.queue_handler.cleanup()

    async def _cleanup_ffmpeg(self) -> None:
        """Clean up FFmpeg manager"""
        if self.ffmpeg_mgr:
            self.ffmpeg_mgr.kill_all_processes()

    async def _cleanup_tasks(self) -> None:
        """Clean up tasks"""
        if self._queue_task and not self._queue_task.done():
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                raise CleanupError(f"Error cleaning up queue task: {str(e)}")

    async def _force_cleanup_queue(self) -> None:
        """Force clean up queue handler"""
        if not self.queue_handler:
            raise CleanupError("Queue handler not initialized")
        await self.queue_handler.force_cleanup()

    async def _force_cleanup_ffmpeg(self) -> None:
        """Force clean up FFmpeg manager"""
        if self.ffmpeg_mgr:
            try:
                self.ffmpeg_mgr.kill_all_processes()
            except Exception as e:
                logger.error(f"Error force cleaning FFmpeg processes: {e}")

    async def _force_cleanup_tasks(self) -> None:
        """Force clean up tasks"""
        if self._queue_task and not self._queue_task.done():
            self._queue_task.cancel()

    def set_queue_task(self, task: asyncio.Task) -> None:
        """
        Set the queue processing task for cleanup purposes.

        Args:
            task: Queue processing task to track
        """
        self._queue_task = task

    def get_cleanup_stats(self) -> Dict[str, Any]:
        """
        Get cleanup statistics.

        Returns:
            Dictionary containing cleanup statistics and status
        """
        return {
            "stats": self.tracker.get_cleanup_stats(),
            "strategy": self.strategy.value,
            "active_cleanups": len(self.tracker.active_cleanups),
            "operations": [
                {
                    "stage": op.stage.value,
                    "timeout": op.timeout,
                    "has_force_cleanup": op.force_func is not None,
                }
                for op in self.cleanup_operations
            ],
        }
