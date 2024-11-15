"""Base module containing core VideoArchiver class"""

from __future__ import annotations

import discord
from redbot.core import commands, Config, data_manager
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

from ..config_manager import ConfigManager
from ..update_checker import UpdateChecker
from ..processor import VideoProcessor
from ..utils.video_downloader import VideoDownloader
from ..utils.message_manager import MessageManager
from ..utils.file_ops import cleanup_downloads
from ..queue import EnhancedVideoQueueManager
from ..ffmpeg.ffmpeg_manager import FFmpegManager
from ..database.video_archive_db import VideoArchiveDB
from ..utils.exceptions import VideoArchiverError as ProcessingError

from .guild import initialize_guild_components
from .cleanup import cleanup_resources, force_cleanup_resources
from .commands import setup_commands
from .events import setup_events

logger = logging.getLogger("VideoArchiver")

# Constants for timeouts
UNLOAD_TIMEOUT = 30  # seconds
CLEANUP_TIMEOUT = 15  # seconds

class VideoArchiver(commands.Cog):
    """Archive videos from Discord channels"""

    default_guild_settings = {
        "enabled": False,
        "archive_channel": None,
        "log_channel": None,
        "enabled_channels": [],
        "video_format": "mp4",
        "video_quality": "high",
        "max_file_size": 8,  # MB
        "message_duration": 30,  # seconds
        "message_template": "{author} archived a video from {channel}",
        "concurrent_downloads": 2,
        "enabled_sites": None,  # None means all sites
        "use_database": False,  # Database tracking is off by default
    }

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the cog with proper error handling"""
        self.bot = bot
        self.ready = asyncio.Event()
        self._init_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._unloading = False
        self.db = None

        # Start initialization
        self._init_task = asyncio.create_task(self._initialize())
        self._init_task.add_done_callback(self._init_callback)

        # Set up commands and events
        setup_commands(self)
        setup_events(self)

    def _init_callback(self, task: asyncio.Task) -> None:
        """Handle initialization task completion"""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            asyncio.create_task(self._cleanup())

    async def _initialize(self) -> None:
        """Initialize all components with proper error handling"""
        try:
            # Initialize config first as other components depend on it
            config = Config.get_conf(self, identifier=855847, force_registration=True)
            config.register_guild(**self.default_guild_settings)
            self.config_manager = ConfigManager(config)

            # Set up paths
            self.data_path = Path(data_manager.cog_data_path(self))
            self.download_path = self.data_path / "downloads"
            self.download_path.mkdir(parents=True, exist_ok=True)

            # Clean existing downloads
            await cleanup_downloads(str(self.download_path))

            # Initialize shared FFmpeg manager
            self.ffmpeg_mgr = FFmpegManager()
            logger.info("Initialized shared FFmpeg manager")

            # Initialize components dict first
            self.components: Dict[int, Dict[str, Any]] = {}

            # Initialize components for existing guilds
            for guild in self.bot.guilds:
                try:
                    await initialize_guild_components(self, guild.id)
                except Exception as e:
                    logger.error(f"Failed to initialize guild {guild.id}: {str(e)}")
                    continue

            # Initialize queue manager after components are ready
            queue_path = self.data_path / "queue_state.json"
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            self.queue_manager = EnhancedVideoQueueManager(
                max_retries=3,
                retry_delay=5,
                max_queue_size=1000,
                cleanup_interval=1800,
                max_history_age=86400,
                persistence_path=str(queue_path),
            )

            # Initialize update checker
            self.update_checker = UpdateChecker(self.bot, self.config_manager)

            # Initialize processor with queue manager and shared FFmpeg manager
            self.processor = VideoProcessor(
                self.bot,
                self.config_manager,
                self.components,
                queue_manager=self.queue_manager,
                ffmpeg_mgr=self.ffmpeg_mgr,
                db=self.db,  # Pass database to processor (None by default)
            )

            # Start update checker
            await self.update_checker.start()

            # Set ready flag
            self.ready.set()

            logger.info("VideoArchiver initialization completed successfully")

        except Exception as e:
            logger.error(f"Critical error during initialization: {str(e)}")
            await self._cleanup()
            raise

    async def cog_load(self) -> None:
        """Handle cog loading"""
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            await self._cleanup()
            raise ProcessingError("Cog initialization timed out")
        except Exception as e:
            await self._cleanup()
            raise ProcessingError(f"Error during cog load: {str(e)}")

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded with timeout"""
        self._unloading = True
        try:
            # Create cleanup task with timeout
            cleanup_task = asyncio.create_task(self._cleanup())
            try:
                await asyncio.wait_for(cleanup_task, timeout=UNLOAD_TIMEOUT)
            except asyncio.TimeoutError:
                logger.error("Cog unload timed out, forcing cleanup")
                # Force cleanup of any remaining resources
                await force_cleanup_resources(self)
        except Exception as e:
            logger.error(f"Error during cog unload: {str(e)}")
            await force_cleanup_resources(self)
        finally:
            self._unloading = False

    async def _cleanup(self) -> None:
        """Clean up all resources with proper handling"""
        await cleanup_resources(self)
