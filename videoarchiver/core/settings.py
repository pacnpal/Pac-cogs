"""Module for managing VideoArchiver settings"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

class VideoFormat(Enum):
    """Supported video formats"""
    MP4 = "mp4"
    WEBM = "webm"
    MKV = "mkv"

class VideoQuality(Enum):
    """Video quality presets"""
    LOW = "low"      # 480p
    MEDIUM = "medium"  # 720p
    HIGH = "high"    # 1080p
    ULTRA = "ultra"  # 4K

@dataclass
class SettingDefinition:
    """Defines a setting's properties"""
    name: str
    category: str
    default_value: Any
    description: str
    data_type: type
    required: bool = True
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    choices: Optional[List[Any]] = None
    depends_on: Optional[str] = None

class SettingCategory(Enum):
    """Setting categories"""
    GENERAL = "general"
    CHANNELS = "channels"
    PERMISSIONS = "permissions"
    VIDEO = "video"
    MESSAGES = "messages"
    PERFORMANCE = "performance"
    FEATURES = "features"

class Settings:
    """Manages VideoArchiver settings"""

    # Setting definitions
    SETTINGS = {
        "enabled": SettingDefinition(
            name="enabled",
            category=SettingCategory.GENERAL.value,
            default_value=False,
            description="Whether the archiver is enabled for this guild",
            data_type=bool
        ),
        "archive_channel": SettingDefinition(
            name="archive_channel",
            category=SettingCategory.CHANNELS.value,
            default_value=None,
            description="Channel where archived videos are posted",
            data_type=int,
            required=False
        ),
        "log_channel": SettingDefinition(
            name="log_channel",
            category=SettingCategory.CHANNELS.value,
            default_value=None,
            description="Channel for logging archiver actions",
            data_type=int,
            required=False
        ),
        "enabled_channels": SettingDefinition(
            name="enabled_channels",
            category=SettingCategory.CHANNELS.value,
            default_value=[],
            description="Channels to monitor (empty means all channels)",
            data_type=list
        ),
        "allowed_roles": SettingDefinition(
            name="allowed_roles",
            category=SettingCategory.PERMISSIONS.value,
            default_value=[],
            description="Roles allowed to use archiver (empty means all roles)",
            data_type=list
        ),
        "video_format": SettingDefinition(
            name="video_format",
            category=SettingCategory.VIDEO.value,
            default_value=VideoFormat.MP4.value,
            description="Format for archived videos",
            data_type=str,
            choices=[format.value for format in VideoFormat]
        ),
        "video_quality": SettingDefinition(
            name="video_quality",
            category=SettingCategory.VIDEO.value,
            default_value=VideoQuality.HIGH.value,
            description="Quality preset for archived videos",
            data_type=str,
            choices=[quality.value for quality in VideoQuality]
        ),
        "max_file_size": SettingDefinition(
            name="max_file_size",
            category=SettingCategory.VIDEO.value,
            default_value=8,
            description="Maximum file size in MB",
            data_type=int,
            min_value=1,
            max_value=100
        ),
        "message_duration": SettingDefinition(
            name="message_duration",
            category=SettingCategory.MESSAGES.value,
            default_value=30,
            description="Duration to show status messages (seconds)",
            data_type=int,
            min_value=5,
            max_value=300
        ),
        "message_template": SettingDefinition(
            name="message_template",
            category=SettingCategory.MESSAGES.value,
            default_value="{author} archived a video from {channel}",
            description="Template for archive messages",
            data_type=str
        ),
        "concurrent_downloads": SettingDefinition(
            name="concurrent_downloads",
            category=SettingCategory.PERFORMANCE.value,
            default_value=2,
            description="Maximum concurrent downloads",
            data_type=int,
            min_value=1,
            max_value=5
        ),
        "enabled_sites": SettingDefinition(
            name="enabled_sites",
            category=SettingCategory.FEATURES.value,
            default_value=None,
            description="Sites to enable archiving for (None means all sites)",
            data_type=list,
            required=False
        ),
        "use_database": SettingDefinition(
            name="use_database",
            category=SettingCategory.FEATURES.value,
            default_value=False,
            description="Enable database tracking of archived videos",
            data_type=bool
        ),
    }

    @classmethod
    def get_setting_definition(cls, setting: str) -> Optional[SettingDefinition]:
        """Get definition for a setting"""
        return cls.SETTINGS.get(setting)

    @classmethod
    def get_settings_by_category(cls, category: str) -> Dict[str, SettingDefinition]:
        """Get all settings in a category"""
        return {
            name: definition
            for name, definition in cls.SETTINGS.items()
            if definition.category == category
        }

    @classmethod
    def validate_setting(cls, setting: str, value: Any) -> bool:
        """Validate a setting value"""
        definition = cls.get_setting_definition(setting)
        if not definition:
            return False

        # Check type
        if not isinstance(value, definition.data_type):
            return False

        # Check required
        if definition.required and value is None:
            return False

        # Check choices
        if definition.choices and value not in definition.choices:
            return False

        # Check numeric bounds
        if isinstance(value, (int, float)):
            if definition.min_value is not None and value < definition.min_value:
                return False
            if definition.max_value is not None and value > definition.max_value:
                return False

        return True

    @property
    def default_guild_settings(self) -> Dict[str, Any]:
        """Default settings for guild configuration"""
        return {
            name: definition.default_value
            for name, definition in self.SETTINGS.items()
        }

    @classmethod
    def get_setting_help(cls, setting: str) -> Optional[str]:
        """Get help text for a setting"""
        definition = cls.get_setting_definition(setting)
        if not definition:
            return None

        help_text = [
            f"Setting: {definition.name}",
            f"Category: {definition.category}",
            f"Description: {definition.description}",
            f"Type: {definition.data_type.__name__}",
            f"Required: {definition.required}",
            f"Default: {definition.default_value}"
        ]

        if definition.choices:
            help_text.append(f"Choices: {', '.join(map(str, definition.choices))}")
        if definition.min_value is not None:
            help_text.append(f"Minimum: {definition.min_value}")
        if definition.max_value is not None:
            help_text.append(f"Maximum: {definition.max_value}")
        if definition.depends_on:
            help_text.append(f"Depends on: {definition.depends_on}")

        return "\n".join(help_text)
