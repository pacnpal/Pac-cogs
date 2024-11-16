"""Module for managing cleanup operations in the video processor"""

import logging
import asyncio
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Set
from datetime import datetime

logger = logging.getLogger("VideoArchiver")

class CleanupStage(Enum):
    """Cleanup stages"""
    QUEUE = "queue"
    FFMPEG = "ffmpeg"
    TASKS = "tasks"
    RESOURCES = "resources"

class CleanupStrategy(Enum):
    """Cleanup strategies"""
    NORMAL = "normal"
    FORCE = "force"
    GRACEFUL = "graceful"

@dataclass
class CleanupResult:
    """Result of a cleanup operation"""
    success: bool
    stage: CleanupStage
    error: Optional[str] = None
    duration: float = 0.0

class CleanupTracker:
    """Tracks cleanup operations"""

    def __init__(self):
        self.cleanup_history: List[Dict[str, Any]] = []
        self.active_cleanups: Set[str] = set()
        self.start_times: Dict[str, datetime] = {}
        self.stage_results: Dict[str, List[CleanupResult]] = {}

    def start_cleanup(self, cleanup_id: str) -> None:
        """Start tracking a cleanup operation"""
        self.active_cleanups.add(cleanup_id)
        self.start_times[cleanup_id] = datetime.utcnow()
        self.stage_results[cleanup_id] = []

    def record_stage_result(
        self,
        cleanup_id: str,
        result: CleanupResult
    ) -> None:
        """Record result of a cleanup stage"""
        if cleanup_id in self.stage_results:
            self.stage_results[cleanup_id].append(result)

    def end_cleanup(self, cleanup_id: str) -> None:
        """End tracking a cleanup operation"""
        if cleanup_id in self.active_cleanups:
            end_time = datetime.utcnow()
            self.cleanup_history.append({
                "id": cleanup_id,
                "start_time": self.start_times[cleanup_id],
                "end_time": end_time,
                "duration": (end_time - self.start_times[cleanup_id]).total_seconds(),
                "results": self.stage_results[cleanup_id]
            })
            self.active_cleanups.remove(cleanup_id)
            self.start_times.pop(cleanup_id)
            self.stage_results.pop(cleanup_id)

    def get_cleanup_stats(self) -> Dict[str, Any]:
        """Get cleanup statistics"""
        return {
            "total_cleanups": len(self.cleanup_history),
            "active_cleanups": len(self.active_cleanups),
            "success_rate": self._calculate_success_rate(),
            "average_duration": self._calculate_average_duration(),
            "stage_success_rates": self._calculate_stage_success_rates()
        }

    def _calculate_success_rate(self) -> float:
        """Calculate overall cleanup success rate"""
        if not self.cleanup_history:
            return 1.0
        successful = sum(
            1 for cleanup in self.cleanup_history
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

    def __init__(
        self,
        queue_handler,
        ffmpeg_mgr: Optional[object] = None,
        strategy: CleanupStrategy = CleanupStrategy.NORMAL
    ):
        self.queue_handler = queue_handler
        self.ffmpeg_mgr = ffmpeg_mgr
        self.strategy = strategy
        self._queue_task: Optional[asyncio.Task] = None
        self.tracker = CleanupTracker()

    async def cleanup(self) -> None:
        """Perform normal cleanup of resources"""
        cleanup_id = f"cleanup_{datetime.utcnow().timestamp()}"
        self.tracker.start_cleanup(cleanup_id)
        
        try:
            logger.info("Starting normal cleanup...")
            
            # Clean up in stages
            stages = [
                (CleanupStage.QUEUE, self._cleanup_queue),
                (CleanupStage.FFMPEG, self._cleanup_ffmpeg),
                (CleanupStage.TASKS, self._cleanup_tasks)
            ]

            for stage, cleanup_func in stages:
                try:
                    start_time = datetime.utcnow()
                    await cleanup_func()
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    self.tracker.record_stage_result(
                        cleanup_id,
                        CleanupResult(True, stage, duration=duration)
                    )
                except Exception as e:
                    logger.error(f"Error in {stage.value} cleanup: {e}")
                    self.tracker.record_stage_result(
                        cleanup_id,
                        CleanupResult(False, stage, str(e))
                    )
                    if self.strategy != CleanupStrategy.GRACEFUL:
                        raise

            logger.info("Normal cleanup completed successfully")

        except Exception as e:
            logger.error(f"Error during normal cleanup: {str(e)}", exc_info=True)
            raise
        finally:
            self.tracker.end_cleanup(cleanup_id)

    async def force_cleanup(self) -> None:
        """Force cleanup of resources when normal cleanup fails"""
        cleanup_id = f"force_cleanup_{datetime.utcnow().timestamp()}"
        self.tracker.start_cleanup(cleanup_id)
        
        try:
            logger.info("Starting force cleanup...")

            # Force cleanup in stages
            stages = [
                (CleanupStage.QUEUE, self._force_cleanup_queue),
                (CleanupStage.FFMPEG, self._force_cleanup_ffmpeg),
                (CleanupStage.TASKS, self._force_cleanup_tasks)
            ]

            for stage, cleanup_func in stages:
                try:
                    start_time = datetime.utcnow()
                    await cleanup_func()
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    self.tracker.record_stage_result(
                        cleanup_id,
                        CleanupResult(True, stage, duration=duration)
                    )
                except Exception as e:
                    logger.error(f"Error in force {stage.value} cleanup: {e}")
                    self.tracker.record_stage_result(
                        cleanup_id,
                        CleanupResult(False, stage, str(e))
                    )

            logger.info("Force cleanup completed")

        except Exception as e:
            logger.error(f"Error during force cleanup: {str(e)}", exc_info=True)
        finally:
            self.tracker.end_cleanup(cleanup_id)

    async def _cleanup_queue(self) -> None:
        """Clean up queue handler"""
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

    async def _force_cleanup_queue(self) -> None:
        """Force clean up queue handler"""
        await self.queue_handler.force_cleanup()

    async def _force_cleanup_ffmpeg(self) -> None:
        """Force clean up FFmpeg manager"""
        if self.ffmpeg_mgr:
            self.ffmpeg_mgr.kill_all_processes()

    async def _force_cleanup_tasks(self) -> None:
        """Force clean up tasks"""
        if self._queue_task and not self._queue_task.done():
            self._queue_task.cancel()

    def set_queue_task(self, task: asyncio.Task) -> None:
        """Set the queue processing task for cleanup purposes"""
        self._queue_task = task

    def get_cleanup_stats(self) -> Dict[str, Any]:
        """Get cleanup statistics"""
        return {
            "stats": self.tracker.get_cleanup_stats(),
            "strategy": self.strategy.value,
            "active_cleanups": len(self.tracker.active_cleanups)
        }
