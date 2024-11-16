"""Base module containing core VideoArchiver class"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from redbot.core.bot import Red
from redbot.core.commands import GroupCog

from .settings import Settings
from .lifecycle import LifecycleManager
from .component_manager import ComponentManager, ComponentState
from .error_handler import error_manager, handle_command_error
from .response_handler import response_manager
from .commands import setup_archiver_commands, setup_database_commands, setup_settings_commands
from .events import setup_events

logger = logging.getLogger("VideoArchiver")

class CogStatus:
    """Tracks cog status and health"""

    def __init__(self):
        self.start_time = datetime.utcnow()
        self.last_error: Optional[str] = None
        self.error_count = 0
        self.command_count = 0
        self.last_command_time: Optional[datetime] = None
        self.health_checks: Dict[str, bool] = {}

    def record_error(self, error: str) -> None:
        """Record an error occurrence"""
        self.last_error = error
        self.error_count += 1

    def record_command(self) -> None:
        """Record a command execution"""
        self.command_count += 1
        self.last_command_time = datetime.utcnow()

    def update_health_check(self, check: str, status: bool) -> None:
        """Update health check status"""
        self.health_checks[check] = status

    def get_status(self) -> Dict[str, Any]:
        """Get current status"""
        return {
            "uptime": (datetime.utcnow() - self.start_time).total_seconds(),
            "last_error": self.last_error,
            "error_count": self.error_count,
            "command_count": self.command_count,
            "last_command": self.last_command_time.isoformat() if self.last_command_time else None,
            "health_checks": self.health_checks.copy()
        }

class ComponentAccessor:
    """Provides safe access to components"""

    def __init__(self, component_manager: ComponentManager):
        self._component_manager = component_manager

    def get_component(self, name: str) -> Optional[Any]:
        """Get a component with state validation"""
        component = self._component_manager.get(name)
        if component and component.state == ComponentState.READY:
            return component
        return None

    def get_component_status(self, name: str) -> Dict[str, Any]:
        """Get component status"""
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
        self.status = CogStatus()

        # Set up commands
        setup_archiver_commands(self)
        setup_database_commands(self)
        setup_settings_commands(self)

        # Set up events
        setup_events(self)

        # Register cleanup handlers
        self.lifecycle_manager.register_cleanup_handler(self._cleanup_handler)

    async def cog_load(self) -> None:
        """Handle cog loading"""
        try:
            await self.lifecycle_manager.handle_load()
            await self._start_health_monitoring()
        except Exception as e:
            self.status.record_error(str(e))
            raise

    async def cog_unload(self) -> None:
        """Handle cog unloading"""
        try:
            await self.lifecycle_manager.handle_unload()
        except Exception as e:
            self.status.record_error(str(e))
            raise

    async def cog_command_error(self, ctx, error):
        """Handle command errors"""
        self.status.record_error(str(error))
        await handle_command_error(ctx, error)

    async def cog_before_invoke(self, ctx) -> bool:
        """Pre-command hook"""
        self.status.record_command()
        return True

    async def _start_health_monitoring(self) -> None:
        """Start health monitoring tasks"""
        asyncio.create_task(self._monitor_component_health())
        asyncio.create_task(self._monitor_system_health())

    async def _monitor_component_health(self) -> None:
        """Monitor component health"""
        while True:
            try:
                component_status = self.component_manager.get_component_status()
                for name, status in component_status.items():
                    self.status.update_health_check(
                        f"component_{name}",
                        status["state"] == ComponentState.READY.value
                    )
            except Exception as e:
                logger.error(f"Error monitoring component health: {e}")
            await asyncio.sleep(60)  # Check every minute

    async def _monitor_system_health(self) -> None:
        """Monitor system health metrics"""
        while True:
            try:
                # Check queue health
                queue_manager = self.queue_manager
                if queue_manager:
                    queue_status = await queue_manager.get_queue_status()
                    self.status.update_health_check(
                        "queue_health",
                        queue_status["active"] and not queue_status["stalled"]
                    )

                # Check processor health
                processor = self.processor
                if processor:
                    processor_status = await processor.get_status()
                    self.status.update_health_check(
                        "processor_health",
                        processor_status["active"]
                    )

            except Exception as e:
                logger.error(f"Error monitoring system health: {e}")
            await asyncio.sleep(30)  # Check every 30 seconds

    async def _cleanup_handler(self) -> None:
        """Custom cleanup handler"""
        try:
            # Perform any custom cleanup
            pass
        except Exception as e:
            logger.error(f"Error in cleanup handler: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive cog status"""
        return {
            "cog": self.status.get_status(),
            "lifecycle": self.lifecycle_manager.get_status(),
            "components": self.component_manager.get_component_status(),
            "errors": error_manager.tracker.get_error_stats()
        }

    # Component property accessors
    @property
    def processor(self):
        """Get the processor component"""
        return self.component_accessor.get_component("processor")

    @property
    def queue_manager(self):
        """Get the queue manager component"""
        return self.component_accessor.get_component("queue_manager")

    @property
    def config_manager(self):
        """Get the config manager component"""
        return self.component_accessor.get_component("config_manager")

    @property
    def ffmpeg_mgr(self):
        """Get the FFmpeg manager component"""
        return self.component_accessor.get_component("ffmpeg_mgr")

    @property
    def data_path(self):
        """Get the data path"""
        return self.component_accessor.get_component("data_path")

    @property
    def download_path(self):
        """Get the download path"""
        return self.component_accessor.get_component("download_path")
