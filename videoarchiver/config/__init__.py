"""Configuration management module"""

try:
    # Try relative imports first
    from .exceptions import (
        ConfigurationError,
        ValidationError,
        PermissionError,
        LoadError,
        SaveError,
        MigrationError,
        SchemaError,
        DiscordAPIError,
    )
    from .channel_manager import ChannelManager
    from .role_manager import RoleManager
    from .settings_formatter import SettingsFormatter
    from .validation_manager import ValidationManager
except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.config.exceptions import (
        ConfigurationError,
        ValidationError,
        PermissionError,
        LoadError,
        SaveError,
        MigrationError,
        SchemaError,
        DiscordAPIError,
    )
    # from videoarchiver.config.channel_manager import ChannelManager
    # from videoarchiver.config.role_manager import RoleManager
    # from videoarchiver.config.settings_formatter import SettingsFormatter
    # from videoarchiver.config.validation_manager import ValidationManager

__all__ = [
    'ConfigurationError',
    'ValidationError',
    'PermissionError',
    'LoadError',
    'SaveError',
    'MigrationError',
    'SchemaError',
    'DiscordAPIError',
    'ChannelManager',
    'RoleManager',
    'SettingsFormatter',
    'ValidationManager',
]
