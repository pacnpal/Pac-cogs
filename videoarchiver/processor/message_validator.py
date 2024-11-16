"""Message validation functionality for video processing"""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List, Any, Callable, Set
from datetime import datetime
import discord

logger = logging.getLogger("VideoArchiver")

class ValidationResult(Enum):
    """Possible validation results"""
    VALID = "valid"
    INVALID = "invalid"
    IGNORED = "ignored"

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

    @classmethod
    def from_message(cls, message: discord.Message, settings: Dict[str, Any]) -> 'ValidationContext':
        """Create context from message"""
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

@dataclass
class ValidationRule:
    """Defines a validation rule"""
    name: str
    description: str
    validate: Callable[[ValidationContext], Tuple[bool, Optional[str]]]
    enabled: bool = True
    priority: int = 0

class ValidationCache:
    """Caches validation results"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._cache: Dict[int, Dict[str, Any]] = {}
        self._access_times: Dict[int, datetime] = {}

    def add(self, message_id: int, result: Dict[str, Any]) -> None:
        """Add validation result to cache"""
        if len(self._cache) >= self.max_size:
            self._cleanup_oldest()
        self._cache[message_id] = result
        self._access_times[message_id] = datetime.utcnow()

    def get(self, message_id: int) -> Optional[Dict[str, Any]]:
        """Get cached validation result"""
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

    def __init__(self):
        self.rules: List[ValidationRule] = [
            ValidationRule(
                name="content_check",
                description="Check if message has content to process",
                validate=self._validate_content,
                priority=1
            ),
            ValidationRule(
                name="guild_enabled",
                description="Check if archiving is enabled for guild",
                validate=self._validate_guild_enabled,
                priority=2
            ),
            ValidationRule(
                name="channel_enabled",
                description="Check if channel is enabled for archiving",
                validate=self._validate_channel,
                priority=3
            ),
            ValidationRule(
                name="user_roles",
                description="Check if user has required roles",
                validate=self._validate_user_roles,
                priority=4
            )
        ]
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

    def __init__(self):
        self.rule_manager = ValidationRuleManager()
        self.cache = ValidationCache()
        self.validation_stats: Dict[str, int] = {
            "total": 0,
            "valid": 0,
            "invalid": 0,
            "ignored": 0,
            "cached": 0
        }

    async def validate_message(
        self,
        message: discord.Message,
        settings: Dict
    ) -> Tuple[bool, Optional[str]]:
        """Validate if a message should be processed"""
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
                valid, reason = rule.validate(ctx)
                if not valid:
                    self.validation_stats["invalid"] += 1
                    # Cache result
                    self.cache.add(message.id, {
                        "valid": False,
                        "reason": reason,
                        "rule": rule.name
                    })
                    return False, reason
            except Exception as e:
                logger.error(f"Error in validation rule {rule.name}: {e}")
                return False, f"Validation error: {str(e)}"

        # Message passed all rules
        self.validation_stats["valid"] += 1
        self.cache.add(message.id, {
            "valid": True,
            "reason": None
        })
        return True, None

    def get_stats(self) -> Dict[str, Any]:
        """Get validation statistics"""
        return {
            "validation_stats": self.validation_stats.copy(),
            "rules": [
                {
                    "name": rule.name,
                    "description": rule.description,
                    "enabled": rule.enabled,
                    "priority": rule.priority
                }
                for rule in self.rule_manager.rules
            ]
        }

    def clear_cache(self, message_id: Optional[int] = None) -> None:
        """Clear validation cache"""
        if message_id:
            self.cache._cache.pop(message_id, None)
            self.cache._access_times.pop(message_id, None)
        else:
            self.cache = ValidationCache(self.cache.max_size)
