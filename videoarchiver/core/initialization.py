"""Module for handling VideoArchiver initialization"""

import logging
import asyncio
import traceback
from pathlib import Path
from typing import Dict, Any, Optional
from redbot.core import Config, data_manager

from ..config_manager import ConfigManager
from ..ffmpeg.ffmpeg_manager import FFmpegManager
from ..queue import EnhancedVideoQueueManager
from ..processor import VideoProcessor
from ..update_checker import UpdateChecker
from .guild import initialize_guild_components
from .cleanup import cleanup_resources, force_cleanup_resources
from ..utils.file_ops import cleanup_downloads
from ..utils.exceptions import VideoArchiverError as ProcessingError

logger = logging.getLogger("VideoArchiver")

class InitializationTracker:
    """Tracks initialization progress"""

    def __init__(self):
        self.total_steps = 8  # Total number of initialization steps
        self.current_step = 0
        self.current_component = ""
        self.errors: Dict[str, str] = {}

    def start_step(self, component: str) -> None:
        """Start a new initialization step"""
        self.current_step += 1
        self.current_component = component
        logger.info(f"Initializing {component} ({self.current_step}/{self.total_steps})")

    def record_error(self, component: str, error: str) -> None:
        """Record an initialization error"""
        self.errors[component] = error
        logger.error(f"Error initializing {component}: {error}")

    def get_progress(self) -> Dict[str, Any]:
        """Get current initialization progress"""
        return {
            "progress": (self.current_step / self.total_steps) * 100,
            "current_component": self.current_component,
            "errors": self.errors.copy()
        }

class ComponentInitializer:
    """Handles initialization of individual components"""

    def __init__(self, cog, tracker: InitializationTracker):
        self.cog = cog
        self.tracker = tracker

    async def init_config(self) -> None:
        """Initialize configuration manager"""
        self.tracker.start_step("Config Manager")
        try:
            config = Config.get_conf(self.cog, identifier=855847, force_registration=True)
            config.register_guild(**self.cog.default_guild_settings)
            self.cog.config_manager = ConfigManager(config)
            logger.info("Config manager initialized")
        except Exception as e:
            self.tracker.record_error("Config Manager", str(e))
            raise

    async def init_paths(self) -> None:
        """Initialize data paths"""
        self.tracker.start_step("Paths")
        try:
            self.cog.data_path = Path(data_manager.cog_data_path(self.cog))
            self.cog.download_path = self.cog.data_path / "downloads"
            self.cog.download_path.mkdir(parents=True, exist_ok=True)
            logger.info("Paths initialized")
        except Exception as e:
            self.tracker.record_error("Paths", str(e))
            raise

    async def init_ffmpeg(self) -> None:
        """Initialize FFmpeg manager"""
        self.tracker.start_step("FFmpeg Manager")
        try:
            self.cog.ffmpeg_mgr = FFmpegManager()
            logger.info("FFmpeg manager initialized")
        except Exception as e:
            self.tracker.record_error("FFmpeg Manager", str(e))
            raise

    async def init_queue(self) -> None:
        """Initialize queue manager"""
        self.tracker.start_step("Queue Manager")
        try:
            queue_path = self.cog.data_path / "queue_state.json"
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            self.cog.queue_manager = EnhancedVideoQueueManager(
                max_retries=3,
                retry_delay=5,
                max_queue_size=1000,
                cleanup_interval=1800,
                max_history_age=86400,
                persistence_path=str(queue_path),
            )
            await self.cog.queue_manager.initialize()
            logger.info("Queue manager initialized")
        except Exception as e:
            self.tracker.record_error("Queue Manager", str(e))
            raise

    async def init_processor(self) -> None:
        """Initialize video processor"""
        self.tracker.start_step("Video Processor")
        try:
            self.cog.processor = VideoProcessor(
                self.cog.bot,
                self.cog.config_manager,
                self.cog.components,
                queue_manager=self.cog.queue_manager,
                ffmpeg_mgr=self.cog.ffmpeg_mgr,
                db=self.cog.db,
            )
            logger.info("Video processor initialized")
        except Exception as e:
            self.tracker.record_error("Video Processor", str(e))
            raise

    async def init_guilds(self) -> None:
        """Initialize guild components"""
        self.tracker.start_step("Guild Components")
        errors = []
        for guild in self.cog.bot.guilds:
            try:
                await initialize_guild_components(self.cog, guild.id)
            except Exception as e:
                errors.append(f"Guild {guild.id}: {str(e)}")
                logger.error(f"Failed to initialize guild {guild.id}: {str(e)}")
        if errors:
            self.tracker.record_error("Guild Components", "; ".join(errors))

    async def init_update_checker(self) -> None:
        """Initialize update checker"""
        self.tracker.start_step("Update Checker")
        try:
            self.cog.update_checker = UpdateChecker(self.cog.bot, self.cog.config_manager)
            await self.cog.update_checker.start()
            logger.info("Update checker initialized")
        except Exception as e:
            self.tracker.record_error("Update Checker", str(e))
            raise

    async def start_queue_processing(self) -> None:
        """Start queue processing"""
        self.tracker.start_step("Queue Processing")
        try:
            self.cog._queue_task = asyncio.create_task(
                self.cog.queue_manager.process_queue(self.cog.processor.process_video)
            )
            logger.info("Queue processing started")
        except Exception as e:
            self.tracker.record_error("Queue Processing", str(e))
            raise

class InitializationManager:
    """Manages VideoArchiver initialization"""

    def __init__(self, cog):
        self.cog = cog
        self.tracker = InitializationTracker()
        self.component_initializer = ComponentInitializer(cog, self.tracker)

    async def initialize(self) -> None:
        """Initialize all components"""
        try:
            # Initialize components in sequence
            await self.component_initializer.init_config()
            await self.component_initializer.init_paths()
            
            # Clean existing downloads
            try:
                await cleanup_downloads(str(self.cog.download_path))
            except Exception as e:
                logger.warning(f"Download cleanup error: {e}")
            
            await self.component_initializer.init_ffmpeg()
            await self.component_initializer.init_queue()
            await self.component_initializer.init_processor()
            await self.component_initializer.init_guilds()
            await self.component_initializer.init_update_checker()
            await self.component_initializer.start_queue_processing()

            # Set ready flag
            self.cog.ready.set()
            logger.info("VideoArchiver initialization completed successfully")

        except Exception as e:
            logger.error(f"Error during initialization: {str(e)}")
            await cleanup_resources(self.cog)
            raise

    def get_progress(self) -> Dict[str, Any]:
        """Get initialization progress"""
        return self.tracker.get_progress()

# Global initialization manager instance
init_manager: Optional[InitializationManager] = None

async def initialize_cog(cog) -> None:
    """Initialize all components with proper error handling"""
    global init_manager
    init_manager = InitializationManager(cog)
    await init_manager.initialize()

def init_callback(cog, task: asyncio.Task) -> None:
    """Handle initialization task completion"""
    try:
        task.result()
        logger.info("Initialization completed successfully")
    except asyncio.CancelledError:
        logger.warning("Initialization was cancelled")
        asyncio.create_task(cleanup_resources(cog))
    except Exception as e:
        logger.error(f"Initialization failed: {str(e)}\n{traceback.format_exc()}")
        asyncio.create_task(cleanup_resources(cog))
