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

[REST OF FILE CONTENT REMAINS THE SAME]
