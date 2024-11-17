"""Configuration management for VideoArchiver"""

import logging
import asyncio
from typing import Dict, Any, Optional, List, Union
import discord # type: ignore
from redbot.core import Config # type: ignore

from .config.validation_manager import ValidationManager
from .config.settings_formatter import SettingsFormatter
from .config.channel_manager import ChannelManager
from .config.role_manager import RoleManager
from .utils.exceptions import ConfigurationError as ConfigError

logger = logging.getLogger("VideoArchiver")

class ConfigManager:
    """Manages guild configurations for VideoArchiver"""

    default_guild = {
        "enabled": False,
        "archive_channel": None,
        "notification_channel": None,
        "log_channel": None,
        "monitored_channels": [],
        "allowed_roles": [],
        "video_format": "mp4",
        "video_quality": 1080,
        "max_file_size": 8,
        "delete_after_repost": True,
        "message_duration": 24,
        "message_template": "Video from {username} in #{channel}\nOriginal: {original_message}",
        "enabled_sites": [],
        "concurrent_downloads": 3,
        "disable_update_check": False,
        "last_update_check": None,
        "max_retries": 3,
        "retry_delay": 5,
        "discord_retry_attempts": 3,
        "discord_retry_delay": 5,
        "use_database": False,
    }

    def __init__(self, bot_config: Config):
        """Initialize configuration managers"""
        self.config = bot_config
        self.config.register_guild(**self.default_guild)
        
        # Initialize managers
        self.validation_manager = ValidationManager()
        self.settings_formatter = SettingsFormatter()
        self.channel_manager = ChannelManager(self)
        self.role_manager = RoleManager(self)
        
        # Thread safety
        self._config_locks: Dict[int, asyncio.Lock] = {}

    async def _get_guild_lock(self, guild_id: int) -> asyncio.Lock:
        """Get or create a lock for guild-specific config operations"""
        if guild_id not in self._config_locks:
            self._config_locks[guild_id] = asyncio.Lock()
        return self._config_locks[guild_id]

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Get all settings for a guild"""
        try:
            async with await self._get_guild_lock(guild_id):
                return await self.config.guild_from_id(guild_id).all()
        except Exception as e:
            logger.error(f"Failed to get guild settings for {guild_id}: {e}")
            raise ConfigError(f"Failed to get guild settings: {str(e)}")

    async def update_setting(
        self,
        guild_id: int,
        setting: str,
        value: Any
    ) -> None:
        """Update a specific setting for a guild"""
        try:
            if setting not in self.default_guild:
                raise ConfigError(f"Invalid setting: {setting}")
            
            # Validate setting
            self.validation_manager.validate_setting(setting, value)
            
            async with await self._get_guild_lock(guild_id):
                await self.config.guild_from_id(guild_id).set_raw(setting, value=value)
                
        except Exception as e:
            logger.error(f"Failed to update setting {setting} for guild {guild_id}: {e}")
            raise ConfigError(f"Failed to update setting: {str(e)}")

    async def get_setting(
        self,
        guild_id: int,
        setting: str
    ) -> Any:
        """Get a specific setting for a guild"""
        try:
            if setting not in self.default_guild:
                raise ConfigError(f"Invalid setting: {setting}")
            
            async with await self._get_guild_lock(guild_id):
                return await self.config.guild_from_id(guild_id).get_raw(setting)
                
        except Exception as e:
            logger.error(f"Failed to get setting {setting} for guild {guild_id}: {e}")
            raise ConfigError(f"Failed to get setting: {str(e)}")

    async def toggle_setting(
        self,
        guild_id: int,
        setting: str
    ) -> bool:
        """Toggle a boolean setting for a guild"""
        try:
            if setting not in self.default_guild:
                raise ConfigError(f"Invalid setting: {setting}")
            
            async with await self._get_guild_lock(guild_id):
                current = await self.get_setting(guild_id, setting)
                if not isinstance(current, bool):
                    raise ConfigError(f"Setting {setting} is not a boolean")
                
                await self.update_setting(guild_id, setting, not current)
                return not current
                
        except Exception as e:
            logger.error(f"Failed to toggle setting {setting} for guild {guild_id}: {e}")
            raise ConfigError(f"Failed to toggle setting: {str(e)}")

    async def add_to_list(
        self,
        guild_id: int,
        setting: str,
        value: Any
    ) -> None:
        """Add a value to a list setting"""
        try:
            if setting not in self.default_guild:
                raise ConfigError(f"Invalid setting: {setting}")
            
            async with await self._get_guild_lock(guild_id):
                async with self.config.guild_from_id(guild_id).get_attr(setting)() as items:
                    if not isinstance(items, list):
                        raise ConfigError(f"Setting {setting} is not a list")
                    if value not in items:
                        items.append(value)
                        
        except Exception as e:
            logger.error(f"Failed to add to list {setting} for guild {guild_id}: {e}")
            raise ConfigError(f"Failed to add to list: {str(e)}")

    async def remove_from_list(
        self,
        guild_id: int,
        setting: str,
        value: Any
    ) -> None:
        """Remove a value from a list setting"""
        try:
            if setting not in self.default_guild:
                raise ConfigError(f"Invalid setting: {setting}")
            
            async with await self._get_guild_lock(guild_id):
                async with self.config.guild_from_id(guild_id).get_attr(setting)() as items:
                    if not isinstance(items, list):
                        raise ConfigError(f"Setting {setting} is not a list")
                    if value in items:
                        items.remove(value)
                        
        except Exception as e:
            logger.error(f"Failed to remove from list {setting} for guild {guild_id}: {e}")
            raise ConfigError(f"Failed to remove from list: {str(e)}")

    async def format_settings_embed(self, guild: discord.Guild) -> discord.Embed:
        """Format guild settings into a Discord embed"""
        try:
            settings = await self.get_guild_settings(guild.id)
            return await self.settings_formatter.format_settings_embed(guild, settings)
        except Exception as e:
            logger.error(f"Failed to format settings embed for guild {guild.id}: {e}")
            raise ConfigError(f"Failed to format settings: {str(e)}")

    # Channel management delegated to channel_manager
    async def get_channel(self, guild: discord.Guild, channel_type: str) -> Optional[discord.TextChannel]:
        """Get a channel by type"""
        return await self.channel_manager.get_channel(guild, channel_type)

    async def get_monitored_channels(self, guild: discord.Guild) -> List[discord.TextChannel]:
        """Get all monitored channels for a guild"""
        return await self.channel_manager.get_monitored_channels(guild)

    # Role management delegated to role_manager
    async def check_user_roles(self, member: discord.Member) -> bool:
        """Check if user has permission based on allowed roles"""
        has_permission, _ = await self.role_manager.check_user_roles(member)
        return has_permission
