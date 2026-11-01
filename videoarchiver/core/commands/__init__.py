"""Command handlers for VideoArchiver"""

from .archiver_commands import setup_archiver_commands
from .database_commands import setup_database_commands
from .settings_commands import setup_settings_commands

__all__ = [
    "setup_archiver_commands",
    "setup_database_commands",
    "setup_settings_commands",
]
