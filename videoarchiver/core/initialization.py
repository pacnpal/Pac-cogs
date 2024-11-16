"""Module for handling VideoArchiver initialization"""

import logging
import asyncio
import traceback
from pathlib import Path
from redbot.core import Config, data_manager

from ..config_manager import ConfigManager
from ..ffmpeg.ffmpeg_manager import FFmpegManager
from ..queue import EnhancedVideoQueueManager
from ..processor import VideoProcessor
from ..update_checker import UpdateChecker
from .guild import initialize_guild_components
from .cleanup import cleanup_downloads, cleanup_resources, force_cleanup_resources
from ..utils.exceptions import VideoArchiverError as ProcessingError

logger = logging.getLogger("VideoArchiver")

# Constants for timeouts
INIT_TIMEOUT = 60  # seconds
COMPONENT_INIT_TIMEOUT = 30  # seconds
CLEANUP_TIMEOUT = 15  # seconds

async def initialize_cog(cog) -> None:
    """Initialize all components with proper error handling"""
    try:
        # Initialize config first as other components depend on it
        config = Config.get_conf(cog, identifier=855847, force_registration=True)
        config.register_guild(**cog.default_guild_settings)
        cog.config_manager = ConfigManager(config)
        logger.info("Config manager initialized")

        # Set up paths
        cog.data_path = Path(data_manager.cog_data_path(cog))
        cog.download_path = cog.data_path / "downloads"
        cog.download_path.mkdir(parents=True, exist_ok=True)
        logger.info("Paths initialized")

        # Clean existing downloads
        try:
            await cleanup_downloads(str(cog.download_path))
        except Exception as e:
            logger.warning(f"Download cleanup error: {e}")

        # Initialize shared FFmpeg manager
        cog.ffmpeg_mgr = FFmpegManager()

        # Initialize queue manager
        queue_path = cog.data_path / "queue_state.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        cog.queue_manager = EnhancedVideoQueueManager(
            max_retries=3,
            retry_delay=5,
            max_queue_size=1000,
            cleanup_interval=1800,
            max_history_age=86400,
            persistence_path=str(queue_path),
        )
        await cog.queue_manager.initialize()

        # Initialize processor
        cog.processor = VideoProcessor(
            cog.bot,
            cog.config_manager,
            cog.components,
            queue_manager=cog.queue_manager,
            ffmpeg_mgr=cog.ffmpeg_mgr,
            db=cog.db,
        )

        # Initialize components for existing guilds
        for guild in cog.bot.guilds:
            try:
                await initialize_guild_components(cog, guild.id)
            except Exception as e:
                logger.error(f"Failed to initialize guild {guild.id}: {str(e)}")
                continue

        # Initialize update checker
        cog.update_checker = UpdateChecker(cog.bot, cog.config_manager)
        await cog.update_checker.start()

        # Start queue processing as a background task
        cog._queue_task = asyncio.create_task(
            cog.queue_manager.process_queue(cog.processor.process_video)
        )

        # Set ready flag
        cog.ready.set()
        logger.info("VideoArchiver initialization completed successfully")

    except Exception as e:
        logger.error(f"Error during initialization: {str(e)}")
        await cleanup_resources(cog)
        raise

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
