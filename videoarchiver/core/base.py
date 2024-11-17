"""Base module containing core VideoArchiver class"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any, Optional, TypedDict, ClassVar, List, Set, Union
from datetime import datetime
from pathlib import Path

import discord  # type: ignore
from redbot.core.bot import Red  # type: ignore
from redbot.core.commands import GroupCog, Context  # type: ignore

try:
    # Try relative imports first
    from .settings import Settings
    from .lifecycle import LifecycleManager, LifecycleState
    from .component_manager import ComponentManager, ComponentState
    from .error_handler import error_manager, handle_command_error
    from .response_handler import ResponseManager
    from .commands.archiver_commands import setup_archiver_commands
    from .commands.database_commands import setup_database_commands
    from .commands.settings_commands import setup_settings_commands
    from .events import setup_events, EventManager
    from ..processor.core import VideoProcessor
    from ..queue.manager import EnhancedVideoQueueManager
    from ..ffmpeg.ffmpeg_manager import FFmpegManager
    from ..database.video_archive_db import VideoArchiveDB
    from ..config_manager import ConfigManager
    from ..utils.exceptions import CogError, ErrorContext, ErrorSeverity
except ImportError:
    # Fall back to absolute imports if relative imports fail
    from videoarchiver.core.settings import Settings
    from videoarchiver.core.lifecycle import LifecycleManager, LifecycleState
    from videoarchiver.core.component_manager import ComponentManager, ComponentState
    from videoarchiver.core.error_handler import error_manager, handle_command_error
    from videoarchiver.core.response_handler import ResponseManager
    from videoarchiver.core.commands.archiver_commands import setup_archiver_commands
    from videoarchiver.core.commands.database_commands import setup_database_commands
    from videoarchiver.core.commands.settings_commands import setup_settings_commands
    from videoarchiver.core.events import setup_events, EventManager
    from videoarchiver.processor.core import VideoProcessor
    from videoarchiver.queue.manager import EnhancedVideoQueueManager
    from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager
    from videoarchiver.database.video_archive_db import VideoArchiveDB
    from videoarchiver.config_manager import ConfigManager
    from videoarchiver.utils.exceptions import CogError, ErrorContext, ErrorSeverity

logger = logging.getLogger("VideoArchiver")


class CogHealthCheck(TypedDict):
    """Type definition for health check status"""

    name: str
    status: bool
    last_check: str
    details: Optional[Dict[str, Any]]


class CogStatus(TypedDict):
    """Type definition for cog status"""

    uptime: float
    last_error: Optional[str]
    error_count: int
    command_count: int
    last_command: Optional[str]
    health_checks: Dict[str, CogHealthCheck]
    state: str
    ready: bool


class StatusTracker:
    """Tracks cog status and health"""

    HEALTH_CHECK_INTERVAL: ClassVar[int] = 30  # Seconds between health checks
    ERROR_THRESHOLD: ClassVar[int] = 100  # Maximum errors before health warning

    def __init__(self) -> None:
        self.start_time = datetime.utcnow()
        self.last_error: Optional[str] = None
        self.error_count = 0
        self.command_count = 0
        self.last_command_time: Optional[datetime] = None
        self.health_checks: Dict[str, CogHealthCheck] = {}

    def record_error(self, error: str) -> None:
        """Record an error occurrence"""
        self.last_error = error
        self.error_count += 1

    def record_command(self) -> None:
        """Record a command execution"""
        self.command_count += 1
        self.last_command_time = datetime.utcnow()

    def update_health_check(
        self, name: str, status: bool, details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update health check status"""
        self.health_checks[name] = CogHealthCheck(
            name=name,
            status=status,
            last_check=datetime.utcnow().isoformat(),
            details=details,
        )

    def get_status(self) -> CogStatus:
        """Get current status"""
        return CogStatus(
            uptime=(datetime.utcnow() - self.start_time).total_seconds(),
            last_error=self.last_error,
            error_count=self.error_count,
            command_count=self.command_count,
            last_command=(
                self.last_command_time.isoformat() if self.last_command_time else None
            ),
            health_checks=self.health_checks.copy(),
            state="healthy" if self.is_healthy() else "unhealthy",
            ready=True,
        )

    def is_healthy(self) -> bool:
        """Check if cog is healthy"""
        if self.error_count > self.ERROR_THRESHOLD:
            return False
        return all(check["status"] for check in self.health_checks.values())


class ComponentAccessor:
    """Provides safe access to components"""

    def __init__(self, component_manager: ComponentManager) -> None:
        self._component_manager = component_manager

    def get_component(self, name: str) -> Optional[Any]:
        """
        Get a component with state validation.

        Args:
            name: Component name

        Returns:
            Component instance if ready, None otherwise
        """
        component = self._component_manager.get(name)
        if component and component.state == ComponentState.READY:
            return component
        return None

    def get_component_status(self, name: str) -> Dict[str, Any]:
        """
        Get component status.

        Args:
            name: Component name

        Returns:
            Component status dictionary
        """
        return self._component_manager.get_component_status().get(name, {})


class VideoArchiver(GroupCog, Settings):
    """Archive videos from Discord channels"""

    def __init__(self, bot: Red) -> None:
        """Initialize the cog with minimal setup"""
        super().__init__()
        self.bot = bot
        self.ready = asyncio.Event()

        # Initialize managers
        self.lifecycle_manager = LifecycleManager(self)
        self.component_manager = ComponentManager(self)
        self.component_accessor = ComponentAccessor(self.component_manager)
        self.status_tracker = StatusTracker()
        self.event_manager: Optional[EventManager] = None

        # Initialize task trackers
        self._init_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._queue_task: Optional[asyncio.Task] = None
        self._health_tasks: Set[asyncio.Task] = set()

        # Initialize component storage
        self.components: Dict[int, Dict[str, Any]] = {}
        self.update_checker = None
        self._db = None

        # Set up commands
        setup_archiver_commands(self)
        setup_database_commands(self)
        setup_settings_commands(self)

        # Set up events
        self.event_manager = setup_events(self)

        # Register cleanup handlers
        self.lifecycle_manager.register_cleanup_handler(self._cleanup_handler)

    async def cog_load(self) -> None:
        """
        Handle cog loading.

        Raises:
            CogError: If loading fails
        """
        try:
            await self.lifecycle_manager.handle_load()
            await self._start_health_monitoring()
        except Exception as e:
            error = f"Failed to load cog: {str(e)}"
            self.status_tracker.record_error(error)
            logger.error(error, exc_info=True)
            raise CogError(
                error,
                context=ErrorContext(
                    "VideoArchiver", "cog_load", None, ErrorSeverity.CRITICAL
                ),
            )

    async def cog_unload(self) -> None:
        """
        Handle cog unloading.

        Raises:
            CogError: If unloading fails
        """
        try:
            # Cancel health monitoring
            for task in self._health_tasks:
                task.cancel()
            self._health_tasks.clear()

            await self.lifecycle_manager.handle_unload()
        except Exception as e:
            error = f"Failed to unload cog: {str(e)}"
            self.status_tracker.record_error(error)
            logger.error(error, exc_info=True)
            raise CogError(
                error,
                context=ErrorContext(
                    "VideoArchiver", "cog_unload", None, ErrorSeverity.CRITICAL
                ),
            )

    async def cog_command_error(self, ctx: Context, error: Exception) -> None:
        """Handle command errors"""
        self.status_tracker.record_error(str(error))
        await handle_command_error(ctx, error)

    async def cog_before_invoke(self, ctx: Context) -> bool:
        """Pre-command hook"""
        self.status_tracker.record_command()
        return True

    async def _start_health_monitoring(self) -> None:
        """Start health monitoring tasks"""
        self._health_tasks.add(asyncio.create_task(self._monitor_component_health()))
        self._health_tasks.add(asyncio.create_task(self._monitor_system_health()))

    async def _monitor_component_health(self) -> None:
        """Monitor component health"""
        while True:
            try:
                component_status = self.component_manager.get_component_status()
                for name, status in component_status.items():
                    self.status_tracker.update_health_check(
                        f"component_{name}",
                        status["state"] == ComponentState.READY.name,
                        status,
                    )
            except Exception as e:
                logger.error(f"Error monitoring component health: {e}", exc_info=True)
            await asyncio.sleep(self.status_tracker.HEALTH_CHECK_INTERVAL)

    async def _monitor_system_health(self) -> None:
        """Monitor system health metrics"""
        while True:
            try:
                # Check queue health
                if queue_manager := self.queue_manager:
                    queue_status = await queue_manager.get_queue_status()
                    self.status_tracker.update_health_check(
                        "queue_health",
                        queue_status["active"] and not queue_status["stalled"],
                        queue_status,
                    )

                # Check processor health
                if processor := self.processor:
                    processor_status = await processor.get_status()
                    self.status_tracker.update_health_check(
                        "processor_health", processor_status["active"], processor_status
                    )

                # Check database health
                if db := self.db:
                    db_status = await db.get_status()
                    self.status_tracker.update_health_check(
                        "database_health", db_status["connected"], db_status
                    )

                # Check event system health
                if self.event_manager:
                    event_stats = self.event_manager.get_stats()
                    self.status_tracker.update_health_check(
                        "event_health", event_stats["health"], event_stats
                    )

            except Exception as e:
                logger.error(f"Error monitoring system health: {e}", exc_info=True)
            await asyncio.sleep(self.status_tracker.HEALTH_CHECK_INTERVAL)

    async def _cleanup_handler(self) -> None:
        """Custom cleanup handler"""
        try:
            # Cancel health monitoring tasks
            for task in self._health_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            self._health_tasks.clear()

        except Exception as e:
            logger.error(f"Error in cleanup handler: {e}", exc_info=True)

    def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive cog status.

        Returns:
            Dictionary containing cog status information
        """
        return {
            "cog": self.status_tracker.get_status(),
            "lifecycle": self.lifecycle_manager.get_status(),
            "components": self.component_manager.get_component_status(),
            "errors": error_manager.tracker.get_error_stats(),
            "events": self.event_manager.get_stats() if self.event_manager else None,
        }

    # Component property accessors
    @property
    def processor(self) -> Optional[VideoProcessor]:
        """Get the processor component"""
        return self.component_accessor.get_component("processor")

    @property
    def queue_manager(self) -> Optional[EnhancedVideoQueueManager]:
        """Get the queue manager component"""
        return self.component_accessor.get_component("queue_manager")

    @property
    def config_manager(self) -> Optional[ConfigManager]:
        """Get the config manager component"""
        return self.component_accessor.get_component("config_manager")

    @property
    def ffmpeg_mgr(self) -> Optional[FFmpegManager]:
        """Get the FFmpeg manager component"""
        return self.component_accessor.get_component("ffmpeg_mgr")

    @property
    def db(self) -> Optional[VideoArchiveDB]:
        """Get the database component"""
        return self._db

    @db.setter
    def db(self, value: VideoArchiveDB) -> None:
        """Set the database component"""
        self._db = value

    @property
    def data_path(self) -> Optional[Path]:
        """Get the data path"""
        return self.component_accessor.get_component("data_path")

    @property
    def download_path(self) -> Optional[Path]:
        """Get the download path"""
        return self.component_accessor.get_component("download_path")

    @property
    def queue_handler(self):
        """Get the queue handler from processor"""
        if processor := self.processor:
            return processor.queue_handler
        return None
