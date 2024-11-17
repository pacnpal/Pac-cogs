"""Command handlers for VideoArchiver"""

from .core.commands.archiver_commands import setup_archiver_commands
from .core.commands.database_commands import setup_database_commands
from .core.commands.settings_commands import setup_settings_commands

__all__ = [
    'setup_archiver_commands',
    'setup_database_commands',
    'setup_settings_commands'
]
