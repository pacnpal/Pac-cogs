"""Command handlers for VideoArchiver"""

from videoarchiver.core.commands.archiver_commands import setup_archiver_commands
from videoarchiver.core.commands.database_commands import setup_database_commands
from videoarchiver.core.commands.settings_commands import setup_settings_commands

__all__ = [
    'setup_archiver_commands',
    'setup_database_commands',
    'setup_settings_commands'
]
