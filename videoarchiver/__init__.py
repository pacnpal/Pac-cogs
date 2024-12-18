"""VideoArchiver cog for Red-DiscordBot"""

import sys
import asyncio
import logging
import importlib
from typing import Optional
from redbot.core.bot import Red  # type: ignore

# Force reload of all modules
modules_to_reload = [
    "utils.exceptions",
    "utils",
    "processor",
    "processor.core",
    "processor.queue_processor",
    "queue",
    "queue.types",  # Added types module
    "queue.models",
    "queue.manager",
    "queue.cleaners",
    "queue.cleaners.guild_cleaner",
    "queue.cleaners.history_cleaner",
    "queue.cleaners.tracking_cleaner",
    "queue.monitoring",
    "queue.recovery_manager",
    "queue.state_manager",
    "ffmpeg",
    "ffmpeg.binary_manager",
    "ffmpeg.encoder_params",
    "ffmpeg.exceptions",
    "ffmpeg.ffmpeg_downloader",
    "ffmpeg.ffmpeg_manager",
    "ffmpeg.gpu_detector",
    "ffmpeg.process_manager",
    "ffmpeg.verification_manager",
    "ffmpeg.video_analyzer",
    "database",
    "database.connection_manager",
    "database.query_manager",
    "database.schema_manager",
    "database.video_archive_db",
    "config",
    "config.channel_manager",
    "config.exceptions",
    "config.role_manager",
    "config.settings_formatter",
    "config.validation_manager",
    "core",
    "core.base",
    "core.cleanup",
    "core.commands",
    "core.commands.archiver_commands",
    "core.commands.database_commands",
    "core.commands.settings_commands",
    "core.component_manager",
    "core.error_handler",
    "core.events",
    "core.guild",
    "core.initialization",
    "core.lifecycle",
    "core.response_handler",
    "core.settings",
]

# Remove modules to force fresh import
for module in modules_to_reload:
    if module in sys.modules:
        del sys.modules[module]

    # try:
    # Try relative imports first
    from . import utils
    from . import processor
    from . import queue
    from . import ffmpeg
    from . import database
    from . import config
    from . import core
    from .core.base import VideoArchiver
    from .core.initialization import initialize_cog, init_callback
    from .core.cleanup import cleanup_resources
    from .utils.exceptions import (
        VideoArchiverError,
        CommandError,
        EventError,
        CogError,
        ErrorContext,
        ErrorSeverity,
        ProcessingError,
    )

    # except ImportError:
    # Fall back to absolute imports if relative imports fail
    #  from videoarchiver import utils
    #  from videoarchiver import processor
    #  from videoarchiver import queue
    #  from videoarchiver import ffmpeg
    #  from videoarchiver import database
    #  from videoarchiver import config
    #  from videoarchiver import core
    # from videoarchiver.core.base import VideoArchiver
    # from videoarchiver.core.initialization import initialize_cog, init_callback
    # from videoarchiver.core.cleanup import cleanup_resources
    # from videoarchiver.utils.exceptions import (
    #    VideoArchiverError,
    #    CommandError,
    #    EventError,
    #    CogError,
    #    ErrorContext,
    #    ErrorSeverity,
    #    ProcessingError,
    # )

    # Reload all modules
    importlib.reload(utils)
    importlib.reload(processor)
    importlib.reload(queue)
    importlib.reload(ffmpeg)
    importlib.reload(database)
    importlib.reload(config)
    importlib.reload(core)

# Import all submodules
from database import *
from ffmpeg import *
from queue import *
from processor import *
from config_manager import *
from update_checker import *
from queue.cleaners import *
from database import *
from utils import *
from core import *
from config import *

logger = logging.getLogger("VideoArchiver")

# Track initialization task
_init_task: Optional[asyncio.Task] = None

# Version information
__version__ = "1.0.0"
__author__ = "VideoArchiver Team"
__description__ = "Video archiving cog for Red-DiscordBot"


async def setup(bot: Red) -> None:
    """Load VideoArchiver with proper initialization."""
    try:
        # Create cog instance
        cog = VideoArchiver(bot)

        # Start initialization in background
        global _init_task
        _init_task = asyncio.create_task(initialize_cog(cog))
        _init_task.add_done_callback(lambda t: init_callback(cog, t))

        # Add cog to bot
        await bot.add_cog(cog)

        logger.info("VideoArchiver cog loaded successfully")

    except Exception as e:
        logger.error(f"Failed to load VideoArchiver: {str(e)}")
        if _init_task and not _init_task.done():
            _init_task.cancel()
        raise


async def teardown(bot: Red) -> None:
    """Clean up when unloading."""
    try:
        # Cancel initialization if still running
        if _init_task and not _init_task.done():
            _init_task.cancel()

        # Remove cog and clean up resources
        if "VideoArchiver" in bot.cogs:
            cog = bot.get_cog("VideoArchiver")
            if cog:
                await cleanup_resources(cog)
            await bot.remove_cog("VideoArchiver")

        logger.info("VideoArchiver cog unloaded successfully")

    except Exception as e:
        logger.error(f"Error during teardown: {str(e)}")
        raise


__all__ = [
    # Core classes
    "VideoArchiver",
    "VideoArchiveDB",
    "FFmpegManager",
    "EnhancedVideoQueueManager",
    "VideoProcessor",
    "ConfigManager",
    "UpdateChecker",
    "QueueCleaner",
    "QueueStateManager",
    "QueueMetricsManager",
    "QueueProcessor",
    "BinaryManager",
    "EncoderParams",
    "GPUDetector",
    "ProcessManager",
    "DatabaseConnectionManager",
    "DatabaseQueryManager",
    "DatabaseSchemaManager",
    "CleanupManager",
    "MessageHandler",
    "CompressionManager",
    "DirectoryManager",
    "DownloadManager",
    "FileOperations",
    # Base exceptions
    "VideoArchiverError",
    "CommandError",
    "EventError",
    "CogError",
    "ErrorContext",
    "ErrorSeverity",
    "ProcessingError",
    # Setup functions
    "setup",
    "teardown",
]
