"""Module for managing VideoArchiver settings"""

from typing import Dict, Any, List, Optional, Union, TypedDict, ClassVar
from dataclasses import dataclass, field
from enum import Enum, auto

try:
    # Try relative imports first
    from ..utils.exceptions import ConfigurationError, ErrorContext, ErrorSeverity
except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.utils.exceptions import ConfigurationError, ErrorContext, ErrorSeverity


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

class SettingCategory(Enum):
    """Setting categories"""
    GENERAL = auto()
    CHANNELS = auto()
    PERMISSIONS = auto()
    VIDEO = auto()
    MESSAGES = auto()
    PERFORMANCE = auto()
    FEATURES = auto()

class ValidationResult(TypedDict):
    """Type definition for validation result"""
    valid: bool
    error: Optional[str]
    details: Dict[str, Any]

@dataclass
class SettingDefinition:
    """Defines a setting's properties"""
    name: str
    category: SettingCategory
    default_value: Any
    description: str
    data_type: type
    required: bool = True
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    choices: Optional[List[Any]] = None
    depends_on: Optional[str] = None
    validation_func: Optional[callable] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate setting definition"""
        if self.choices and self.default_value not in self.choices:
            raise ConfigurationError(
                f"Default value {self.default_value} not in choices {self.choices}",
                context=ErrorContext(
                    "Settings",
                    "definition_validation",
                    {"setting": self.name},
                    ErrorSeverity.HIGH
                )
            )

        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ConfigurationError(
                    f"Min value {self.min_value} greater than max value {self.max_value}",
                    context=ErrorContext(
                        "Settings",
                        "definition_validation",
                        {"setting": self.name},
                        ErrorSeverity.HIGH
                    )
                )

class Settings:
    """Manages VideoArchiver settings"""

    # Setting definitions
    SETTINGS: ClassVar[Dict[str, SettingDefinition]] = {
        "enabled": SettingDefinition(
            name="enabled",
            category=SettingCategory.GENERAL,
            default_value=False,
            description="Whether the archiver is enabled for this guild",
            data_type=bool
        ),
        "archive_channel": SettingDefinition(
            name="archive_channel",
            category=SettingCategory.CHANNELS,
            default_value=None,
            description="Channel where archived videos are posted",
            data_type=int,
            required=False,
            error_message="Archive channel must be a valid channel ID"
        ),
        "log_channel": SettingDefinition(
            name="log_channel",
            category=SettingCategory.CHANNELS,
            default_value=None,
            description="Channel for logging archiver actions",
            data_type=int,
            required=False,
            error_message="Log channel must be a valid channel ID"
        ),
        "enabled_channels": SettingDefinition(
            name="enabled_channels",
            category=SettingCategory.CHANNELS,
            default_value=[],
            description="Channels to monitor (empty means all channels)",
            data_type=list,
            error_message="Enabled channels must be a list of valid channel IDs"
        ),
        "allowed_roles": SettingDefinition(
            name="allowed_roles",
            category=SettingCategory.PERMISSIONS,
            default_value=[],
            description="Roles allowed to use archiver (empty means all roles)",
            data_type=list,
            error_message="Allowed roles must be a list of valid role IDs"
        ),
        "video_format": SettingDefinition(
            name="video_format",
            category=SettingCategory.VIDEO,
            default_value=VideoFormat.MP4.value,
            description="Format for archived videos",
            data_type=str,
            choices=[format.value for format in VideoFormat],
            error_message=f"Video format must be one of: {', '.join(f.value for f in VideoFormat)}"
        ),
        "video_quality": SettingDefinition(
            name="video_quality",
            category=SettingCategory.VIDEO,
            default_value=VideoQuality.HIGH.value,
            description="Quality preset for archived videos",
            data_type=str,
            choices=[quality.value for quality in VideoQuality],
            error_message=f"Video quality must be one of: {', '.join(q.value for q in VideoQuality)}"
        ),
        "max_file_size": SettingDefinition(
            name="max_file_size",
            category=SettingCategory.VIDEO,
            default_value=8,
            description="Maximum file size in MB",
            data_type=int,
            min_value=1,
            max_value=100,
            error_message="Max file size must be between 1 and 100 MB"
        ),
        "message_duration": SettingDefinition(
            name="message_duration",
            category=SettingCategory.MESSAGES,
            default_value=30,
            description="Duration to show status messages (seconds)",
            data_type=int,
            min_value=5,
            max_value=300,
            error_message="Message duration must be between 5 and 300 seconds"
        ),
        "message_template": SettingDefinition(
            name="message_template",
            category=SettingCategory.MESSAGES,
            default_value="{author} archived a video from {channel}",
            description="Template for archive messages",
            data_type=str,
            error_message="Message template must contain {author} and {channel} placeholders"
        ),
        "concurrent_downloads": SettingDefinition(
            name="concurrent_downloads",
            category=SettingCategory.PERFORMANCE,
            default_value=2,
            description="Maximum concurrent downloads",
            data_type=int,
            min_value=1,
            max_value=5,
            error_message="Concurrent downloads must be between 1 and 5"
        ),
        "enabled_sites": SettingDefinition(
            name="enabled_sites",
            category=SettingCategory.FEATURES,
            default_value=None,
            description="Sites to enable archiving for (None means all sites)",
            data_type=list,
            required=False,
            error_message="Enabled sites must be a list of valid site identifiers"
        ),
        "use_database": SettingDefinition(
            name="use_database",
            category=SettingCategory.FEATURES,
            default_value=False,
            description="Enable database tracking of archived videos",
            data_type=bool
        ),
    }

    @classmethod
    def get_setting_definition(cls, setting: str) -> Optional[SettingDefinition]:
        """
        Get definition for a setting.
        
        Args:
            setting: Setting name
            
        Returns:
            Setting definition or None if not found
        """
        return cls.SETTINGS.get(setting)

    @classmethod
    def get_settings_by_category(cls, category: SettingCategory) -> Dict[str, SettingDefinition]:
        """
        Get all settings in a category.
        
        Args:
            category: Setting category
            
        Returns:
            Dictionary of settings in the category
        """
        return {
            name: definition
            for name, definition in cls.SETTINGS.items()
            if definition.category == category
        }

    @classmethod
    def validate_setting(cls, setting: str, value: Any) -> ValidationResult:
        """
        Validate a setting value.
        
        Args:
            setting: Setting name
            value: Value to validate
            
        Returns:
            Validation result dictionary
            
        Raises:
            ConfigurationError: If setting definition is not found
        """
        definition = cls.get_setting_definition(setting)
        if not definition:
            raise ConfigurationError(
                f"Unknown setting: {setting}",
                context=ErrorContext(
                    "Settings",
                    "validation",
                    {"setting": setting},
                    ErrorSeverity.HIGH
                )
            )

        details = {
            "setting": setting,
            "value": value,
            "type": type(value).__name__,
            "expected_type": definition.data_type.__name__
        }

        # Check type
        if not isinstance(value, definition.data_type):
            return ValidationResult(
                valid=False,
                error=f"Invalid type: expected {definition.data_type.__name__}, got {type(value).__name__}",
                details=details
            )

        # Check required
        if definition.required and value is None:
            return ValidationResult(
                valid=False,
                error="Required setting cannot be None",
                details=details
            )

        # Check choices
        if definition.choices and value not in definition.choices:
            return ValidationResult(
                valid=False,
                error=f"Value must be one of: {', '.join(map(str, definition.choices))}",
                details=details
            )

        # Check numeric bounds
        if isinstance(value, (int, float)):
            if definition.min_value is not None and value < definition.min_value:
                return ValidationResult(
                    valid=False,
                    error=f"Value must be at least {definition.min_value}",
                    details=details
                )
            if definition.max_value is not None and value > definition.max_value:
                return ValidationResult(
                    valid=False,
                    error=f"Value must be at most {definition.max_value}",
                    details=details
                )

        # Custom validation
        if definition.validation_func:
            try:
                result = definition.validation_func(value)
                if not result:
                    return ValidationResult(
                        valid=False,
                        error=definition.error_message or "Validation failed",
                        details=details
                    )
            except Exception as e:
                return ValidationResult(
                    valid=False,
                    error=str(e),
                    details=details
                )

        return ValidationResult(
            valid=True,
            error=None,
            details=details
        )

    @property
    def default_guild_settings(self) -> Dict[str, Any]:
        """
        Default settings for guild configuration.
        
        Returns:
            Dictionary of default settings
        """
        return {
            name: definition.default_value
            for name, definition in self.SETTINGS.items()
        }

    @classmethod
    def get_setting_help(cls, setting: str) -> Optional[str]:
        """
        Get help text for a setting.
        
        Args:
            setting: Setting name
            
        Returns:
            Help text or None if setting not found
        """
        definition = cls.get_setting_definition(setting)
        if not definition:
            return None

        help_text = [
            f"Setting: {definition.name}",
            f"Category: {definition.category.name}",
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
        if definition.error_message:
            help_text.append(f"Error: {definition.error_message}")

        return "\n".join(help_text)
