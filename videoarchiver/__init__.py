"""VideoArchiver cog for Red-DiscordBot"""

import sys
import asyncio
import logging
import importlib
from typing import Optional
from redbot.core.bot import Red

# Force reload of all modules
modules_to_reload = [
    'videoarchiver.utils.exceptions',
    'videoarchiver.utils',
    'videoarchiver.processor',
    'videoarchiver.processor.core',
    'videoarchiver.processor.queue_processor',
    'videoarchiver.queue',
    'videoarchiver.queue.models',
    'videoarchiver.queue.manager',
    'videoarchiver.queue.cleaners',
    'videoarchiver.queue.cleaners.guild_cleaner',
    'videoarchiver.queue.cleaners.history_cleaner',
    'videoarchiver.queue.cleaners.tracking_cleaner',
    'videoarchiver.queue.monitoring',
    'videoarchiver.queue.recovery_manager',
    'videoarchiver.queue.state_manager',
    'videoarchiver.ffmpeg',
    'videoarchiver.ffmpeg.binary_manager',
    'videoarchiver.ffmpeg.encoder_params',
    'videoarchiver.ffmpeg.exceptions',
    'videoarchiver.ffmpeg.ffmpeg_downloader',
    'videoarchiver.ffmpeg.ffmpeg_manager',
    'videoarchiver.ffmpeg.gpu_detector',
    'videoarchiver.ffmpeg.process_manager',
    'videoarchiver.ffmpeg.verification_manager',
    'videoarchiver.ffmpeg.video_analyzer',
    'videoarchiver.database',
    'videoarchiver.database.connection_manager',
    'videoarchiver.database.query_manager',
    'videoarchiver.database.schema_manager',
    'videoarchiver.database.video_archive_db',
    'videoarchiver.config',
    'videoarchiver.config.channel_manager',
    'videoarchiver.config.exceptions',
    'videoarchiver.config.role_manager',
    'videoarchiver.config.settings_formatter',
    'videoarchiver.config.validation_manager',
    'videoarchiver.core',
    'videoarchiver.core.base',
    'videoarchiver.core.cleanup',
    'videoarchiver.core.commands',
    'videoarchiver.core.commands.archiver_commands',
    'videoarchiver.core.commands.database_commands',
    'videoarchiver.core.commands.settings_commands',
    'videoarchiver.core.component_manager',
    'videoarchiver.core.error_handler',
    'videoarchiver.core.events',
    'videoarchiver.core.guild',
    'videoarchiver.core.initialization',
    'videoarchiver.core.lifecycle',
    'videoarchiver.core.response_handler',
    'videoarchiver.core.settings'
]

# Remove modules to force fresh import
for module in modules_to_reload:
    if module in sys.modules:
        del sys.modules[module]

# Import and reload utils
import videoarchiver.utils
importlib.reload(videoarchiver.utils)

# Import and reload processor
import videoarchiver.processor
importlib.reload(videoarchiver.processor)

# Import and reload queue
import videoarchiver.queue
importlib.reload(videoarchiver.queue)

# Import and reload ffmpeg
import videoarchiver.ffmpeg
importlib.reload(videoarchiver.ffmpeg)

# Import and reload database
import videoarchiver.database
importlib.reload(videoarchiver.database)

# Import and reload config
import videoarchiver.config
importlib.reload(videoarchiver.config)

# Import and reload core
import videoarchiver.core
importlib.reload(videoarchiver.core)

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
    ProcessingError
)
from .database import VideoArchiveDB
from .ffmpeg import FFmpegManager
from .queue import EnhancedVideoQueueManager
from .processor import VideoProcessor
from .config_manager import ConfigManager
from .update_checker import UpdateChecker

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
    "teardown"
]
