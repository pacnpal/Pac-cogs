"""Cleanup functionality for VideoArchiver"""

import asyncio
import logging
import os
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, Optional, TypedDict, ClassVar

try:
    # Try relative imports first
    from ..utils.file_ops import cleanup_downloads
    from ..utils.exceptions import CleanupError, ErrorContext, ErrorSeverity
except ImportError:
    # Fall back to absolute imports if relative imports fail
    from videoarchiver.utils.file_ops import cleanup_downloads
    from videoarchiver.utils.exceptions import CleanupError, ErrorContext, ErrorSeverity

if TYPE_CHECKING:
    try:
        from .base import VideoArchiver
    except ImportError:
        from videoarchiver.core.base import VideoArchiver

logger = logging.getLogger("VideoArchiver")

class CleanupPhase(Enum):
    """Cleanup phases"""
    INITIALIZATION = auto()
    UPDATE_CHECKER = auto()
    PROCESSOR = auto()
    QUEUE_MANAGER = auto()
    COMPONENTS = auto()
    FFMPEG = auto()
    DOWNLOADS = auto()
    REFERENCES = auto()

class CleanupStatus(Enum):
    """Cleanup status"""
    SUCCESS = auto()
    TIMEOUT = auto()
    ERROR = auto()
    SKIPPED = auto()

class CleanupResult(TypedDict):
    """Type definition for cleanup result"""
    phase: CleanupPhase
    status: CleanupStatus
    error: Optional[str]
    duration: float
    timestamp: str

class CleanupManager:
    """Manages cleanup operations"""

    CLEANUP_TIMEOUT: ClassVar[int] = 5  # Reduced timeout to 5 seconds
    FORCE_CLEANUP_TIMEOUT: ClassVar[int] = 3  # Even shorter timeout for force cleanup

    def __init__(self) -> None:
        self.results: Dict[CleanupPhase, CleanupResult] = {}

    def record_result(
        self,
        phase: CleanupPhase,
        status: CleanupStatus,
        error: Optional[str] = None,
        duration: float = 0.0
    ) -> None:
        """Record result of a cleanup phase"""
        self.results[phase] = CleanupResult(
            phase=phase,
            status=status,
            error=error,
            duration=duration,
            timestamp=datetime.utcnow().isoformat()
        )

    def get_results(self) -> Dict[CleanupPhase, CleanupResult]:
        """Get cleanup results"""
        return self.results.copy()

async def cleanup_resources(cog: "VideoArchiver") -> None:
    """
    Clean up all resources with proper handling.
    
    Args:
        cog: VideoArchiver cog instance
        
    Raises:
        CleanupError: If cleanup fails
    """
    cleanup_manager = CleanupManager()
    start_time = datetime.utcnow()

    try:
        logger.info("Starting resource cleanup...")

        # Cancel initialization if still running
        if cog._init_task and not cog._init_task.done():
            phase_start = datetime.utcnow()
            try:
                logger.info("Cancelling initialization task")
                cog._init_task.cancel()
                await asyncio.wait_for(cog._init_task, timeout=cleanup_manager.CLEANUP_TIMEOUT)
                cleanup_manager.record_result(
                    CleanupPhase.INITIALIZATION,
                    CleanupStatus.SUCCESS,
                    duration=(datetime.utcnow() - phase_start).total_seconds()
                )
            except (asyncio.TimeoutError, asyncio.CancelledError) as e:
                logger.warning("Initialization task cancellation timed out")
                cleanup_manager.record_result(
                    CleanupPhase.INITIALIZATION,
                    CleanupStatus.TIMEOUT,
                    str(e),
                    (datetime.utcnow() - phase_start).total_seconds()
                )

        # Stop update checker
        if hasattr(cog, "update_checker") and cog.update_checker:
            phase_start = datetime.utcnow()
            try:
                logger.info("Stopping update checker")
                await asyncio.wait_for(
                    cog.update_checker.stop(),
                    timeout=cleanup_manager.CLEANUP_TIMEOUT
                )
                cleanup_manager.record_result(
                    CleanupPhase.UPDATE_CHECKER,
                    CleanupStatus.SUCCESS,
                    duration=(datetime.utcnow() - phase_start).total_seconds()
                )
            except asyncio.TimeoutError as e:
                logger.warning("Update checker stop timed out")
                cleanup_manager.record_result(
                    CleanupPhase.UPDATE_CHECKER,
                    CleanupStatus.TIMEOUT,
                    str(e),
                    (datetime.utcnow() - phase_start).total_seconds()
                )
            cog.update_checker = None

        # Clean up processor
        if hasattr(cog, "processor") and cog.processor:
            phase_start = datetime.utcnow()
            try:
                logger.info("Cleaning up processor")
                await asyncio.wait_for(
                    cog.processor.cleanup(),
                    timeout=cleanup_manager.CLEANUP_TIMEOUT
                )
                cleanup_manager.record_result(
                    CleanupPhase.PROCESSOR,
                    CleanupStatus.SUCCESS,
                    duration=(datetime.utcnow() - phase_start).total_seconds()
                )
            except asyncio.TimeoutError as e:
                logger.warning("Processor cleanup timed out, forcing cleanup")
                await cog.processor.force_cleanup()
                cleanup_manager.record_result(
                    CleanupPhase.PROCESSOR,
                    CleanupStatus.TIMEOUT,
                    str(e),
                    (datetime.utcnow() - phase_start).total_seconds()
                )
            cog.processor = None

        # Clean up queue manager
        if hasattr(cog, "queue_manager") and cog.queue_manager:
            phase_start = datetime.utcnow()
            try:
                logger.info("Cleaning up queue manager")
                await asyncio.wait_for(
                    cog.queue_manager.cleanup(),
                    timeout=cleanup_manager.CLEANUP_TIMEOUT
                )
                cleanup_manager.record_result(
                    CleanupPhase.QUEUE_MANAGER,
                    CleanupStatus.SUCCESS,
                    duration=(datetime.utcnow() - phase_start).total_seconds()
                )
            except asyncio.TimeoutError as e:
                logger.warning("Queue manager cleanup timed out, forcing stop")
                cog.queue_manager.force_stop()
                cleanup_manager.record_result(
                    CleanupPhase.QUEUE_MANAGER,
                    CleanupStatus.TIMEOUT,
                    str(e),
                    (datetime.utcnow() - phase_start).total_seconds()
                )
            cog.queue_manager = None

        # Clean up components for each guild
        if hasattr(cog, "components"):
            phase_start = datetime.utcnow()
            errors = []
            try:
                logger.info("Cleaning up guild components")
                for guild_id, components in cog.components.items():
                    try:
                        if "message_manager" in components:
                            await components["message_manager"].cancel_all_deletions()
                        if "downloader" in components:
                            components["downloader"] = None
                        if "ffmpeg_mgr" in components:
                            components["ffmpeg_mgr"] = None
                    except Exception as e:
                        errors.append(f"Guild {guild_id}: {str(e)}")

                cog.components.clear()
                status = CleanupStatus.SUCCESS if not errors else CleanupStatus.ERROR
                cleanup_manager.record_result(
                    CleanupPhase.COMPONENTS,
                    status,
                    "\n".join(errors) if errors else None,
                    (datetime.utcnow() - phase_start).total_seconds()
                )
            except Exception as e:
                cleanup_manager.record_result(
                    CleanupPhase.COMPONENTS,
                    CleanupStatus.ERROR,
                    str(e),
                    (datetime.utcnow() - phase_start).total_seconds()
                )

        # Kill any FFmpeg processes
        phase_start = datetime.utcnow()
        try:
            if hasattr(cog, "ffmpeg_mgr") and cog.ffmpeg_mgr:
                logger.info("Killing FFmpeg processes")
                cog.ffmpeg_mgr.kill_all_processes()
                cog.ffmpeg_mgr = None

            # Kill any remaining FFmpeg processes system-wide
            if os.name != 'nt':  # Unix-like systems
                os.system("pkill -9 ffmpeg")
            else:  # Windows
                os.system("taskkill /F /IM ffmpeg.exe")

            cleanup_manager.record_result(
                CleanupPhase.FFMPEG,
                CleanupStatus.SUCCESS,
                duration=(datetime.utcnow() - phase_start).total_seconds()
            )
        except Exception as e:
            cleanup_manager.record_result(
                CleanupPhase.FFMPEG,
                CleanupStatus.ERROR,
                str(e),
                (datetime.utcnow() - phase_start).total_seconds()
            )

        # Clean up download directory
        if hasattr(cog, "download_path") and cog.download_path.exists():
            phase_start = datetime.utcnow()
            try:
                logger.info("Cleaning up download directory")
                await asyncio.wait_for(
                    cleanup_downloads(str(cog.download_path)),
                    timeout=cleanup_manager.CLEANUP_TIMEOUT
                )
                if cog.download_path.exists():
                    cog.download_path.rmdir()
                cleanup_manager.record_result(
                    CleanupPhase.DOWNLOADS,
                    CleanupStatus.SUCCESS,
                    duration=(datetime.utcnow() - phase_start).total_seconds()
                )
            except Exception as e:
                cleanup_manager.record_result(
                    CleanupPhase.DOWNLOADS,
                    CleanupStatus.ERROR,
                    str(e),
                    (datetime.utcnow() - phase_start).total_seconds()
                )

    except Exception as e:
        error = f"Error during cleanup: {str(e)}"
        logger.error(error, exc_info=True)
        raise CleanupError(
            error,
            context=ErrorContext(
                "Cleanup",
                "cleanup_resources",
                {"duration": (datetime.utcnow() - start_time).total_seconds()},
                ErrorSeverity.HIGH
            )
        )
    finally:
        logger.info("Clearing ready flag")
        cog.ready.clear()

        # Log cleanup results
        for phase, result in cleanup_manager.get_results().items():
            status_str = f"{result['status'].name}"
            if result['error']:
                status_str += f" ({result['error']})"
            logger.info(
                f"Cleanup phase {phase.name}: {status_str} "
                f"(Duration: {result['duration']:.2f}s)"
            )

async def force_cleanup_resources(cog: "VideoArchiver") -> None:
    """
    Force cleanup of resources when timeout occurs.
    
    Args:
        cog: VideoArchiver cog instance
    """
    cleanup_manager = CleanupManager()
    start_time = datetime.utcnow()

    try:
        logger.info("Starting force cleanup...")

        # Cancel all tasks immediately
        if hasattr(cog, "processor") and cog.processor:
            phase_start = datetime.utcnow()
            try:
                logger.info("Force cleaning processor")
                await cog.processor.force_cleanup()
                cleanup_manager.record_result(
                    CleanupPhase.PROCESSOR,
                    CleanupStatus.SUCCESS,
                    duration=(datetime.utcnow() - phase_start).total_seconds()
                )
            except Exception as e:
                cleanup_manager.record_result(
                    CleanupPhase.PROCESSOR,
                    CleanupStatus.ERROR,
                    str(e),
                    (datetime.utcnow() - phase_start).total_seconds()
                )
            cog.processor = None

        # Force stop queue manager
        if hasattr(cog, "queue_manager") and cog.queue_manager:
            phase_start = datetime.utcnow()
            try:
                logger.info("Force stopping queue manager")
                cog.queue_manager.force_stop()
                cleanup_manager.record_result(
                    CleanupPhase.QUEUE_MANAGER,
                    CleanupStatus.SUCCESS,
                    duration=(datetime.utcnow() - phase_start).total_seconds()
                )
            except Exception as e:
                cleanup_manager.record_result(
                    CleanupPhase.QUEUE_MANAGER,
                    CleanupStatus.ERROR,
                    str(e),
                    (datetime.utcnow() - phase_start).total_seconds()
                )
            cog.queue_manager = None

        # Kill FFmpeg processes
        phase_start = datetime.utcnow()
        try:
            if hasattr(cog, "ffmpeg_mgr") and cog.ffmpeg_mgr:
                logger.info("Force killing FFmpeg processes")
                cog.ffmpeg_mgr.kill_all_processes()
                cog.ffmpeg_mgr = None

            # Force kill any remaining FFmpeg processes system-wide
            if os.name != 'nt':  # Unix-like systems
                os.system("pkill -9 ffmpeg")
            else:  # Windows
                os.system("taskkill /F /IM ffmpeg.exe")

            cleanup_manager.record_result(
                CleanupPhase.FFMPEG,
                CleanupStatus.SUCCESS,
                duration=(datetime.utcnow() - phase_start).total_seconds()
            )
        except Exception as e:
            cleanup_manager.record_result(
                CleanupPhase.FFMPEG,
                CleanupStatus.ERROR,
                str(e),
                (datetime.utcnow() - phase_start).total_seconds()
            )

        # Clean up download directory
        if hasattr(cog, "download_path") and cog.download_path.exists():
            phase_start = datetime.utcnow()
            try:
                logger.info("Force cleaning download directory")
                await asyncio.wait_for(
                    cleanup_downloads(str(cog.download_path)),
                    timeout=cleanup_manager.FORCE_CLEANUP_TIMEOUT
                )
                if cog.download_path.exists():
                    cog.download_path.rmdir()
                cleanup_manager.record_result(
                    CleanupPhase.DOWNLOADS,
                    CleanupStatus.SUCCESS,
                    duration=(datetime.utcnow() - phase_start).total_seconds()
                )
            except Exception as e:
                cleanup_manager.record_result(
                    CleanupPhase.DOWNLOADS,
                    CleanupStatus.ERROR,
                    str(e),
                    (datetime.utcnow() - phase_start).total_seconds()
                )

        # Clear all components
        phase_start = datetime.utcnow()
        try:
            logger.info("Force clearing components")
            if hasattr(cog, "components"):
                cog.components.clear()
            cleanup_manager.record_result(
                CleanupPhase.COMPONENTS,
                CleanupStatus.SUCCESS,
                duration=(datetime.utcnow() - phase_start).total_seconds()
            )
        except Exception as e:
            cleanup_manager.record_result(
                CleanupPhase.COMPONENTS,
                CleanupStatus.ERROR,
                str(e),
                (datetime.utcnow() - phase_start).total_seconds()
            )

    except Exception as e:
        error = f"Error during force cleanup: {str(e)}"
        logger.error(error, exc_info=True)
    finally:
        logger.info("Clearing ready flag")
        cog.ready.clear()

        # Clear all references
        phase_start = datetime.utcnow()
        try:
            cog.bot = None
            cog.processor = None
            cog.queue_manager = None
            cog.update_checker = None
            cog.ffmpeg_mgr = None
            cog.components = {}
            cog.db = None
            cog._init_task = None
            cog._cleanup_task = None
            if hasattr(cog, '_queue_task'):
                cog._queue_task = None
            cleanup_manager.record_result(
                CleanupPhase.REFERENCES,
                CleanupStatus.SUCCESS,
                duration=(datetime.utcnow() - phase_start).total_seconds()
            )
        except Exception as e:
            cleanup_manager.record_result(
                CleanupPhase.REFERENCES,
                CleanupStatus.ERROR,
                str(e),
                (datetime.utcnow() - phase_start).total_seconds()
            )

        # Log cleanup results
        for phase, result in cleanup_manager.get_results().items():
            status_str = f"{result['status'].name}"
            if result['error']:
                status_str += f" ({result['error']})"
            logger.info(
                f"Force cleanup phase {phase.name}: {status_str} "
                f"(Duration: {result['duration']:.2f}s)"
            )
