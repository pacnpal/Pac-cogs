"""Base module containing core VideoArchiver class"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from redbot.core.bot import Red
from redbot.core.commands import GroupCog

from .initialization import initialize_cog, init_callback
from .error_handler import handle_command_error
from .cleanup import cleanup_resources, force_cleanup_resources
from .commands import setup_archiver_commands, setup_database_commands, setup_settings_commands
from ..utils.exceptions import VideoArchiverError as ProcessingError

logger = logging.getLogger("VideoArchiver")

# Constants for timeouts
UNLOAD_TIMEOUT = 30  # seconds
CLEANUP_TIMEOUT = 15  # seconds

class VideoArchiver(GroupCog):
    """Archive videos from Discord channels"""

    default_guild_settings = {
        "enabled": False,
        "archive_channel": None,
        "log_channel": None,
        "enabled_channels": [],  # Empty list means all channels
        "allowed_roles": [],  # Empty list means all roles
        "video_format": "mp4",
        "video_quality": "high",
        "max_file_size": 8,  # MB
        "message_duration": 30,  # seconds
        "message_template": "{author} archived a video from {channel}",
        "concurrent_downloads": 2,
        "enabled_sites": None,  # None means all sites
        "use_database": False,  # Database tracking is off by default
    }

    def __init__(self, bot: Red) -> None:
        """Initialize the cog with minimal setup"""
        super().__init__()
        self.bot = bot
        self.ready = asyncio.Event()
        self._init_task = None
        self._cleanup_task = None
        self._queue_task = None
        self._unloading = False
        self.db = None
        self.queue_manager = None
        self.processor = None
        self.components = {}
        self.config_manager = None
        self.update_checker = None
        self.ffmpeg_mgr = None
        self.data_path = None
        self.download_path = None

        # Set up commands
        setup_archiver_commands(self)
        setup_database_commands(self)
        setup_settings_commands(self)

        # Set up events - non-blocking
        from .events import setup_events
        setup_events(self)

    async def cog_load(self) -> None:
        """Handle cog loading without blocking"""
        try:
            # Start initialization as background task without waiting
            self._init_task = asyncio.create_task(initialize_cog(self))
            self._init_task.add_done_callback(lambda t: init_callback(self, t))
            logger.info("Initialization started in background")
        except Exception as e:
            # Ensure cleanup on any error
            try:
                await asyncio.wait_for(
                    force_cleanup_resources(self), timeout=CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error("Force cleanup during load error timed out")
            raise ProcessingError(f"Error during cog load: {str(e)}")

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded with proper timeout handling"""
        self._unloading = True
        try:
            # Cancel any pending tasks
            if self._init_task and not self._init_task.done():
                self._init_task.cancel()

            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()

            # Cancel queue processing task if it exists
            if (
                hasattr(self, "_queue_task")
                and self._queue_task
                and not self._queue_task.done()
            ):
                self._queue_task.cancel()
                try:
                    await self._queue_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling queue task: {e}")

            # Try normal cleanup first
            cleanup_task = asyncio.create_task(cleanup_resources(self))
            try:
                await asyncio.wait_for(cleanup_task, timeout=UNLOAD_TIMEOUT)
                logger.info("Normal cleanup completed")
            except (asyncio.TimeoutError, Exception) as e:
                if isinstance(e, asyncio.TimeoutError):
                    logger.warning("Normal cleanup timed out, forcing cleanup")
                else:
                    logger.error(f"Error during normal cleanup: {str(e)}")

                # Cancel normal cleanup and force cleanup
                cleanup_task.cancel()
                try:
                    # Force cleanup with timeout
                    await asyncio.wait_for(
                        force_cleanup_resources(self), timeout=CLEANUP_TIMEOUT
                    )
                    logger.info("Force cleanup completed")
                except asyncio.TimeoutError:
                    logger.error("Force cleanup timed out")
                except Exception as e:
                    logger.error(f"Error during force cleanup: {str(e)}")

        except Exception as e:
            logger.error(f"Error during cog unload: {str(e)}")
        finally:
            self._unloading = False
            # Ensure ready flag is cleared
            self.ready.clear()
            # Clear all references
            self.bot = None
            self.processor = None
            self.queue_manager = None
            self.update_checker = None
            self.ffmpeg_mgr = None
            self.components.clear()
            self.db = None
            self._init_task = None
            self._cleanup_task = None
            if hasattr(self, "_queue_task"):
                self._queue_task = None

    async def cog_command_error(self, ctx, error):
        """Handle command errors"""
        await handle_command_error(ctx, error)
