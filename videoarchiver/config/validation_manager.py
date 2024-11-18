"""Module for validating configuration settings"""

import logging
from typing import Any, Dict, List, Union

try:
    # Try relative imports first
    from .exceptions import ConfigurationError as ConfigError
except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.config.exceptions import ConfigurationError as ConfigError

logger = logging.getLogger("ConfigValidation")


class ValidationManager:
    """Manages validation of configuration settings"""

    # Valid settings constraints
    VALID_VIDEO_FORMATS = ["mp4", "webm", "mkv"]
    MAX_QUALITY_RANGE = (144, 4320)  # 144p to 4K
    MAX_FILE_SIZE_RANGE = (1, 100)  # 1MB to 100MB
    MAX_CONCURRENT_DOWNLOADS = 5
    MAX_MESSAGE_DURATION = 168  # 1 week in hours
    MAX_RETRIES = 10
    MAX_RETRY_DELAY = 30

    def validate_setting(self, setting: str, value: Any) -> None:
        """Validate a setting value against constraints
        
        Args:
            setting: Name of the setting to validate
            value: Value to validate
            
        Raises:
            ConfigError: If validation fails
        """
        try:
            validator = getattr(self, f"_validate_{setting}", None)
            if validator:
                validator(value)
            else:
                self._validate_generic(setting, value)
        except Exception as e:
            logger.error(f"Validation error for {setting}: {e}")
            raise ConfigError(f"Validation error for {setting}: {str(e)}")

    def _validate_video_format(self, value: str) -> None:
        """Validate video format setting"""
        if value not in self.VALID_VIDEO_FORMATS:
            raise ConfigError(
                f"Invalid video format. Must be one of: {', '.join(self.VALID_VIDEO_FORMATS)}"
            )

    def _validate_video_quality(self, value: int) -> None:
        """Validate video quality setting"""
        if not isinstance(value, int) or not (
            self.MAX_QUALITY_RANGE[0] <= value <= self.MAX_QUALITY_RANGE[1]
        ):
            raise ConfigError(
                f"Video quality must be between {self.MAX_QUALITY_RANGE[0]} and {self.MAX_QUALITY_RANGE[1]}"
            )

    def _validate_max_file_size(self, value: Union[int, float]) -> None:
        """Validate max file size setting"""
        if not isinstance(value, (int, float)) or not (
            self.MAX_FILE_SIZE_RANGE[0] <= value <= self.MAX_FILE_SIZE_RANGE[1]
        ):
            raise ConfigError(
                f"Max file size must be between {self.MAX_FILE_SIZE_RANGE[0]} and {self.MAX_FILE_SIZE_RANGE[1]} MB"
            )

    def _validate_concurrent_downloads(self, value: int) -> None:
        """Validate concurrent downloads setting"""
        if not isinstance(value, int) or not (1 <= value <= self.MAX_CONCURRENT_DOWNLOADS):
            raise ConfigError(
                f"Concurrent downloads must be between 1 and {self.MAX_CONCURRENT_DOWNLOADS}"
            )

    def _validate_message_duration(self, value: int) -> None:
        """Validate message duration setting"""
        if not isinstance(value, int) or not (0 <= value <= self.MAX_MESSAGE_DURATION):
            raise ConfigError(
                f"Message duration must be between 0 and {self.MAX_MESSAGE_DURATION} hours"
            )

    def _validate_max_retries(self, value: int) -> None:
        """Validate max retries setting"""
        if not isinstance(value, int) or not (0 <= value <= self.MAX_RETRIES):
            raise ConfigError(
                f"Max retries must be between 0 and {self.MAX_RETRIES}"
            )

    def _validate_retry_delay(self, value: int) -> None:
        """Validate retry delay setting"""
        if not isinstance(value, int) or not (1 <= value <= self.MAX_RETRY_DELAY):
            raise ConfigError(
                f"Retry delay must be between 1 and {self.MAX_RETRY_DELAY} seconds"
            )

    def _validate_message_template(self, value: str) -> None:
        """Validate message template setting"""
        if not isinstance(value, str):
            raise ConfigError("Message template must be a string")

        # Check for required placeholders
        required_placeholders = ["{username}", "{channel}"]
        for placeholder in required_placeholders:
            if placeholder not in value:
                raise ConfigError(f"Message template must contain {placeholder}")

    def _validate_boolean(self, value: bool) -> None:
        """Validate boolean settings"""
        if not isinstance(value, bool):
            raise ConfigError("Value must be a boolean")

    def _validate_list(self, value: List[Any]) -> None:
        """Validate list settings"""
        if not isinstance(value, list):
            raise ConfigError("Value must be a list")

    def _validate_generic(self, setting: str, value: Any) -> None:
        """Generic validation for settings without specific validators"""
        if setting.endswith("_channel") and value is not None:
            if not isinstance(value, int):
                raise ConfigError(f"{setting} must be a channel ID (int) or None")
        elif setting in ["enabled", "delete_after_repost", "disable_update_check", "use_database"]:
            self._validate_boolean(value)
        elif setting in ["monitored_channels", "allowed_roles", "enabled_sites"]:
            self._validate_list(value)

    def validate_all_settings(self, settings: Dict[str, Any]) -> None:
        """Validate all settings in a configuration dictionary
        
        Args:
            settings: Dictionary of settings to validate
            
        Raises:
            ConfigError: If any validation fails
        """
        for setting, value in settings.items():
            self.validate_setting(setting, value)
