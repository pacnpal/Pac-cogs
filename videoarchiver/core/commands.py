"""Command handlers for VideoArchiver"""

# Commands have been moved to the VideoArchiver class in base.py
# This file is kept for backward compatibility and may be removed in a future version

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from videoarchiver.core.base import VideoArchiver

def setup_commands(cog: "VideoArchiver") -> None:
    """Command setup is now handled in the VideoArchiver class"""
    pass  # Commands are now defined in the VideoArchiver class
