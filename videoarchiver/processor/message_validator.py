"""Message validation functionality for video processing"""

import logging
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List, Any, Callable, Set, TypedDict, ClassVar
from datetime import datetime
import discord # type: ignore

try:
    # Try relative imports first
    from ..utils.exceptions import ValidationError
except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.utils.exceptions import ValidationError

logger = logging.getLogger("VideoArchiver")


class ValidationResult(Enum):
    """Possible validation results"""
    VALID = auto()
    INVALID = auto()
    IGNORED = auto()


class ValidationStats(TypedDict):
    """Type definition for validation statistics"""
    total: int
    valid: int
    invalid: int
    ignored: int
    cached: int


class ValidationCacheEntry(TypedDict):
    """Type definition for validation cache entry"""
    valid: bool
    reason: Optional[str]
    rule: Optional[str]
    timestamp: str


@dataclass
class ValidationContext:
    """Context for message validation"""
    message: discord.Message
    settings: Dict[str, Any]
    guild_id: int
    channel_id: int
    author_id: int
    roles: Set[int]
    content_length: int
    attachment_count: int
    is_bot: bool
    timestamp: datetime
    validation_time: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def from_message(cls, message: discord.Message, settings: Dict[str, Any]) -> 'ValidationContext':
        """
        Create context from message.
        
        Args:
            message: Discord message to validate
            settings: Guild settings dictionary
            
        Returns:
            ValidationContext instance
            
        Raises:
            ValidationError: If message or settings are invalid
        """
        if not message.guild:
            raise ValidationError("Message must be from a guild")
        if not settings:
            raise ValidationError("Settings dictionary cannot be empty")

        try:
            return cls(
                message=message,
                settings=settings,
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                author_id=message.author.id,
                roles={role.id for role in message.author.roles},
                content_length=len(message.content) if message.content else 0,
                attachment_count=len(message.attachments),
                is_bot=message.author.bot,
                timestamp=message.created_at
            )
        except Exception as e:
            raise ValidationError(f"Failed to create validation context: {str(e)}")


@dataclass
class ValidationRule:
    """Defines a validation rule"""
    name: str
    description: str
    validate: Callable[[ValidationContext], Tuple[bool, Optional[str]]]
    enabled: bool = True
    priority: int = 0
    error_count: int = field(default=0)
    last_error: Optional[str] = field(default=None)
    last_run: Optional[str] = field(default=None)

    def __post_init__(self) -> None:
        """Validate rule after initialization"""
        if not callable(self.validate):
            raise ValueError("Validate must be a callable")
        if self.priority < 0:
            raise ValueError("Priority must be non-negative")


class ValidationCache:
    """Caches validation results"""

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._cache: Dict[int, ValidationCacheEntry] = {}
        self._access_times: Dict[int, datetime] = {}

    def add(self, message_id: int, result: ValidationCacheEntry) -> None:
        """
        Add validation result to cache.
        
        Args:
            message_id: Discord message ID
            result: Validation result entry
        """
        if len(self._cache) >= self.max_size:
            self._cleanup_oldest()
        self._cache[message_id] = result
        self._access_times[message_id] = datetime.utcnow()

    def get(self, message_id: int) -> Optional[ValidationCacheEntry]:
        """
        Get cached validation result.
        
        Args:
            message_id: Discord message ID
            
        Returns:
            Cached validation entry or None if not found
        """
        if message_id in self._cache:
            self._access_times[message_id] = datetime.utcnow()
            return self._cache[message_id]
        return None

    def _cleanup_oldest(self) -> None:
        """Remove oldest cache entries"""
        if not self._access_times:
            return
        oldest = min(self._access_times.items(), key=lambda x: x[1])[0]
        del self._cache[oldest]
        del self._access_times[oldest]


class ValidationRuleManager:
    """Manages validation rules"""

    DEFAULT_RULES: ClassVar[List[Tuple[str, str, int]]] = [
        ("content_check", "Check if message has content to process", 1),
        ("guild_enabled", "Check if archiving is enabled for guild", 2),
        ("channel_enabled", "Check if channel is enabled for archiving", 3),
        ("user_roles", "Check if user has required roles", 4)
    ]

    def __init__(self) -> None:
        self.rules: List[ValidationRule] = []
        self._initialize_rules()

    def _initialize_rules(self) -> None:
        """Initialize default validation rules"""
        for name, description, priority in self.DEFAULT_RULES:
            validate_method = getattr(self, f"_validate_{name}", None)
            if validate_method:
                self.rules.append(ValidationRule(
                    name=name,
                    description=description,
                    validate=validate_method,
                    priority=priority
                ))
        self.rules.sort(key=lambda x: x.priority)

    def _validate_content(self, ctx: ValidationContext) -> Tuple[bool, Optional[str]]:
        """Validate message content"""
        if not ctx.content_length and not ctx.attachment_count:
            return False, "No content or attachments"
        return True, None

    def _validate_guild_enabled(self, ctx: ValidationContext) -> Tuple[bool, Optional[str]]:
        """Validate guild settings"""
        if not ctx.settings.get("enabled", False):
            return False, "Video archiving disabled for guild"
        return True, None

    def _validate_channel(self, ctx: ValidationContext) -> Tuple[bool, Optional[str]]:
        """Validate channel settings"""
        enabled_channels = ctx.settings.get("enabled_channels", [])
        if enabled_channels and ctx.channel_id not in enabled_channels:
            return False, "Channel not enabled for archiving"
        return True, None

    def _validate_user_roles(self, ctx: ValidationContext) -> Tuple[bool, Optional[str]]:
        """Validate user roles"""
        allowed_roles = ctx.settings.get("allowed_roles", [])
        if allowed_roles and not (ctx.roles & set(allowed_roles)):
            return False, "User does not have required roles"
        return True, None


class MessageValidator:
    """Handles validation of messages for video processing"""

    def __init__(self) -> None:
        self.rule_manager = ValidationRuleManager()
        self.cache = ValidationCache()
        self.validation_stats: ValidationStats = {
            "total": 0,
            "valid": 0,
            "invalid": 0,
            "ignored": 0,
            "cached": 0
        }

    async def validate_message(
        self,
        message: discord.Message,
        settings: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate if a message should be processed.
        
        Args:
            message: Discord message to validate
            settings: Guild settings dictionary
            
        Returns:
            Tuple of (is_valid, reason)
            
        Raises:
            ValidationError: If validation fails unexpectedly
        """
        try:
            self.validation_stats["total"] += 1

            # Check cache
            cached = self.cache.get(message.id)
            if cached:
                self.validation_stats["cached"] += 1
                return cached["valid"], cached.get("reason")

            # Create validation context
            ctx = ValidationContext.from_message(message, settings)

            # Run validation rules
            for rule in self.rule_manager.rules:
                if not rule.enabled:
                    continue

                try:
                    rule.last_run = datetime.utcnow().isoformat()
                    valid, reason = rule.validate(ctx)
                    if not valid:
                        self.validation_stats["invalid"] += 1
                        # Cache result
                        self.cache.add(message.id, ValidationCacheEntry(
                            valid=False,
                            reason=reason,
                            rule=rule.name,
                            timestamp=datetime.utcnow().isoformat()
                        ))
                        return False, reason
                except Exception as e:
                    rule.error_count += 1
                    rule.last_error = str(e)
                    logger.error(f"Error in validation rule {rule.name}: {e}", exc_info=True)
                    raise ValidationError(f"Validation rule {rule.name} failed: {str(e)}")

            # Message passed all rules
            self.validation_stats["valid"] += 1
            self.cache.add(message.id, ValidationCacheEntry(
                valid=True,
                reason=None,
                rule=None,
                timestamp=datetime.utcnow().isoformat()
            ))
            return True, None

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in message validation: {e}", exc_info=True)
            raise ValidationError(f"Validation failed: {str(e)}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get validation statistics.
        
        Returns:
            Dictionary containing validation statistics and rule information
        """
        return {
            "validation_stats": self.validation_stats.copy(),
            "rules": [
                {
                    "name": rule.name,
                    "description": rule.description,
                    "enabled": rule.enabled,
                    "priority": rule.priority,
                    "error_count": rule.error_count,
                    "last_error": rule.last_error,
                    "last_run": rule.last_run
                }
                for rule in self.rule_manager.rules
            ]
        }

    def clear_cache(self, message_id: Optional[int] = None) -> None:
        """
        Clear validation cache.
        
        Args:
            message_id: Optional message ID to clear cache for. If None, clears all cache.
        """
        try:
            if message_id:
                self.cache._cache.pop(message_id, None)
                self.cache._access_times.pop(message_id, None)
            else:
                self.cache = ValidationCache(self.cache.max_size)
        except Exception as e:
            logger.error(f"Error clearing validation cache: {e}", exc_info=True)
