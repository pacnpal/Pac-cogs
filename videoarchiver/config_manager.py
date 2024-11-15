"""Configuration management for VideoArchiver"""
from redbot.core import Config
from typing import Dict, Any, Optional, List, Union, cast
import discord
import logging
from datetime import datetime
import asyncio
from .exceptions import ConfigError, DiscordAPIError

logger = logging.getLogger('VideoArchiver')

class ConfigManager:
    """Manages guild configurations for VideoArchiver"""

    default_guild = {
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
    }

    # Valid settings constraints
    VALID_VIDEO_FORMATS = ["mp4", "webm", "mkv"]
    MAX_QUALITY_RANGE = (144, 4320)  # 144p to 4K
    MAX_FILE_SIZE_RANGE = (1, 100)  # 1MB to 100MB
    MAX_CONCURRENT_DOWNLOADS = 5
    MAX_MESSAGE_DURATION = 168  # 1 week in hours
    MAX_RETRIES = 10
    MAX_RETRY_DELAY = 30

    def __init__(self, bot_config: Config):
        self.config = bot_config
        self.config.register_guild(**self.default_guild)
        self._config_locks: Dict[int, asyncio.Lock] = {}

    async def _get_guild_lock(self, guild_id: int) -> asyncio.Lock:
        """Get or create a lock for guild-specific config operations"""
        if guild_id not in self._config_locks:
            self._config_locks[guild_id] = asyncio.Lock()
        return self._config_locks[guild_id]

    def _validate_setting(self, setting: str, value: Any) -> None:
        """Validate setting value against constraints"""
        try:
            if setting == "video_format" and value not in self.VALID_VIDEO_FORMATS:
                raise ConfigError(f"Invalid video format. Must be one of: {', '.join(self.VALID_VIDEO_FORMATS)}")
            
            elif setting == "video_quality":
                if not isinstance(value, int) or not (self.MAX_QUALITY_RANGE[0] <= value <= self.MAX_QUALITY_RANGE[1]):
                    raise ConfigError(f"Video quality must be between {self.MAX_QUALITY_RANGE[0]} and {self.MAX_QUALITY_RANGE[1]}")
            
            elif setting == "max_file_size":
                if not isinstance(value, (int, float)) or not (self.MAX_FILE_SIZE_RANGE[0] <= value <= self.MAX_FILE_SIZE_RANGE[1]):
                    raise ConfigError(f"Max file size must be between {self.MAX_FILE_SIZE_RANGE[0]} and {self.MAX_FILE_SIZE_RANGE[1]} MB")
            
            elif setting == "concurrent_downloads":
                if not isinstance(value, int) or not (1 <= value <= self.MAX_CONCURRENT_DOWNLOADS):
                    raise ConfigError(f"Concurrent downloads must be between 1 and {self.MAX_CONCURRENT_DOWNLOADS}")
            
            elif setting == "message_duration":
                if not isinstance(value, int) or not (0 <= value <= self.MAX_MESSAGE_DURATION):
                    raise ConfigError(f"Message duration must be between 0 and {self.MAX_MESSAGE_DURATION} hours")
            
            elif setting == "max_retries":
                if not isinstance(value, int) or not (0 <= value <= self.MAX_RETRIES):
                    raise ConfigError(f"Max retries must be between 0 and {self.MAX_RETRIES}")
            
            elif setting == "retry_delay":
                if not isinstance(value, int) or not (1 <= value <= self.MAX_RETRY_DELAY):
                    raise ConfigError(f"Retry delay must be between 1 and {self.MAX_RETRY_DELAY} seconds")
            
            elif setting in ["message_template"] and not isinstance(value, str):
                raise ConfigError("Message template must be a string")
            
            elif setting in ["delete_after_repost", "disable_update_check"] and not isinstance(value, bool):
                raise ConfigError(f"{setting} must be a boolean")
            
        except Exception as e:
            raise ConfigError(f"Validation error for {setting}: {str(e)}")

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Get all settings for a guild with error handling"""
        try:
            async with await self._get_guild_lock(guild_id):
                return await self.config.guild_from_id(guild_id).all()
        except Exception as e:
            logger.error(f"Failed to get guild settings for {guild_id}: {str(e)}")
            raise ConfigError(f"Failed to get guild settings: {str(e)}")

    async def update_setting(self, guild_id: int, setting: str, value: Any) -> None:
        """Update a specific setting for a guild with validation"""
        try:
            if setting not in self.default_guild:
                raise ConfigError(f"Invalid setting: {setting}")
            
            self._validate_setting(setting, value)
            
            async with await self._get_guild_lock(guild_id):
                await self.config.guild_from_id(guild_id).set_raw(setting, value=value)
                
        except Exception as e:
            logger.error(f"Failed to update setting {setting} for guild {guild_id}: {str(e)}")
            raise ConfigError(f"Failed to update setting: {str(e)}")

    async def get_setting(self, guild_id: int, setting: str) -> Any:
        """Get a specific setting for a guild with error handling"""
        try:
            if setting not in self.default_guild:
                raise ConfigError(f"Invalid setting: {setting}")
            
            async with await self._get_guild_lock(guild_id):
                return await self.config.guild_from_id(guild_id).get_raw(setting)
                
        except Exception as e:
            logger.error(f"Failed to get setting {setting} for guild {guild_id}: {str(e)}")
            raise ConfigError(f"Failed to get setting: {str(e)}")

    async def toggle_setting(self, guild_id: int, setting: str) -> bool:
        """Toggle a boolean setting for a guild with validation"""
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
            logger.error(f"Failed to toggle setting {setting} for guild {guild_id}: {str(e)}")
            raise ConfigError(f"Failed to toggle setting: {str(e)}")

    async def add_to_list(self, guild_id: int, setting: str, value: Any) -> None:
        """Add a value to a list setting with validation"""
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
            logger.error(f"Failed to add to list {setting} for guild {guild_id}: {str(e)}")
            raise ConfigError(f"Failed to add to list: {str(e)}")

    async def remove_from_list(self, guild_id: int, setting: str, value: Any) -> None:
        """Remove a value from a list setting with validation"""
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
            logger.error(f"Failed to remove from list {setting} for guild {guild_id}: {str(e)}")
            raise ConfigError(f"Failed to remove from list: {str(e)}")

    async def get_channel(self, guild: discord.Guild, channel_type: str) -> Optional[discord.TextChannel]:
        """Get a channel by type with error handling and validation"""
        try:
            if channel_type not in ["archive", "notification", "log"]:
                raise ConfigError(f"Invalid channel type: {channel_type}")
            
            settings = await self.get_guild_settings(guild.id)
            channel_id = settings.get(f"{channel_type}_channel")
            
            if channel_id is None:
                return None
            
            channel = guild.get_channel(channel_id)
            if channel is None:
                logger.warning(f"Channel {channel_id} not found in guild {guild.id}")
                return None
            
            if not isinstance(channel, discord.TextChannel):
                raise DiscordAPIError(f"Channel {channel_id} is not a text channel")
            
            return channel
            
        except Exception as e:
            logger.error(f"Failed to get {channel_type} channel for guild {guild.id}: {str(e)}")
            raise ConfigError(f"Failed to get channel: {str(e)}")

    async def check_user_roles(self, member: discord.Member) -> bool:
        """Check if user has permission based on allowed roles with error handling"""
        try:
            allowed_roles = await self.get_setting(member.guild.id, "allowed_roles")
            # If no roles are set, allow all users
            if not allowed_roles:
                return True
            return any(role.id in allowed_roles for role in member.roles)
            
        except Exception as e:
            logger.error(f"Failed to check roles for user {member.id} in guild {member.guild.id}: {str(e)}")
            raise ConfigError(f"Failed to check user roles: {str(e)}")

    async def get_monitored_channels(self, guild: discord.Guild) -> List[discord.TextChannel]:
        """Get all monitored channels for a guild with validation"""
        try:
            settings = await self.get_guild_settings(guild.id)
            monitored_channel_ids = settings["monitored_channels"]
            
            # If no channels are set to be monitored, return all text channels
            if not monitored_channel_ids:
                return [channel for channel in guild.channels if isinstance(channel, discord.TextChannel)]
            
            # Otherwise, return only the specified channels
            channels: List[discord.TextChannel] = []
            for channel_id in monitored_channel_ids:
                channel = guild.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    channels.append(channel)
                else:
                    logger.warning(f"Invalid monitored channel {channel_id} in guild {guild.id}")
            
            return channels
            
        except Exception as e:
            logger.error(f"Failed to get monitored channels for guild {guild.id}: {str(e)}")
            raise ConfigError(f"Failed to get monitored channels: {str(e)}")

    async def format_settings_embed(self, guild: discord.Guild) -> discord.Embed:
        """Format guild settings into a Discord embed with error handling"""
        try:
            settings = await self.get_guild_settings(guild.id)
            embed = discord.Embed(
                title="Video Archiver Settings",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            # Get channels with error handling
            archive_channel = guild.get_channel(settings["archive_channel"]) if settings["archive_channel"] else None
            notification_channel = guild.get_channel(settings["notification_channel"]) if settings["notification_channel"] else None
            log_channel = guild.get_channel(settings["log_channel"]) if settings["log_channel"] else None
            
            # Get monitored channels and roles with validation
            monitored_channels = []
            for channel_id in settings["monitored_channels"]:
                channel = guild.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    monitored_channels.append(channel.mention)
                    
            allowed_roles = []
            for role_id in settings["allowed_roles"]:
                role = guild.get_role(role_id)
                if role:
                    allowed_roles.append(role.name)

            # Add fields with proper formatting
            embed.add_field(
                name="Archive Channel",
                value=archive_channel.mention if archive_channel else "Not set",
                inline=False
            )
            embed.add_field(
                name="Notification Channel",
                value=notification_channel.mention if notification_channel else "Same as archive",
                inline=False
            )
            embed.add_field(
                name="Log Channel",
                value=log_channel.mention if log_channel else "Not set",
                inline=False
            )
            embed.add_field(
                name="Monitored Channels",
                value="\n".join(monitored_channels) if monitored_channels else "All channels",
                inline=False
            )
            embed.add_field(
                name="Allowed Roles",
                value=", ".join(allowed_roles) if allowed_roles else "All roles (no restrictions)",
                inline=False
            )

            # Add other settings with validation
            embed.add_field(
                name="Video Format",
                value=settings["video_format"],
                inline=True
            )
            embed.add_field(
                name="Max Quality",
                value=f"{settings['video_quality']}p",
                inline=True
            )
            embed.add_field(
                name="Max File Size",
                value=f"{settings['max_file_size']}MB",
                inline=True
            )
            embed.add_field(
                name="Delete After Repost",
                value=str(settings["delete_after_repost"]),
                inline=True
            )
            embed.add_field(
                name="Message Duration",
                value=f"{settings['message_duration']} hours",
                inline=True
            )
            embed.add_field(
                name="Concurrent Downloads",
                value=str(settings["concurrent_downloads"]),
                inline=True
            )
            embed.add_field(
                name="Update Check Disabled",
                value=str(settings["disable_update_check"]),
                inline=True
            )

            # Add enabled sites with validation
            embed.add_field(
                name="Enabled Sites",
                value=", ".join(settings["enabled_sites"]) if settings["enabled_sites"] else "All sites",
                inline=False
            )

            # Add footer with last update time
            embed.set_footer(text="Last updated")

            return embed
            
        except Exception as e:
            logger.error(f"Failed to format settings embed for guild {guild.id}: {str(e)}")
            raise ConfigError(f"Failed to format settings: {str(e)}")
