"""Module for managing Discord channel configurations"""

import logging
from typing import Dict, List, Optional, Tuple
import discord # type: ignore

try:
    # Try relative imports first
    from .exceptions import (
        ConfigurationError as ConfigError,
        DiscordAPIError,
    )
except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.config.exceptions import (
        ConfigurationError as ConfigError,
        DiscordAPIError,
    )

logger = logging.getLogger("ChannelManager")


class ChannelManager:
    """Manages Discord channel configurations"""

    def __init__(self, config_manager):
        self.config_manager = config_manager

    async def get_channel(
        self, guild: discord.Guild, channel_type: str
    ) -> Optional[discord.TextChannel]:
        """Get a channel by type

        Args:
            guild: Discord guild
            channel_type: Type of channel (archive, notification, log)

        Returns:
            Optional[discord.TextChannel]: Channel if found and valid

        Raises:
            ConfigError: If channel type is invalid
            DiscordAPIError: If channel exists but is invalid type
        """
        try:
            if channel_type not in ["archive", "notification", "log"]:
                raise ConfigError(f"Invalid channel type: {channel_type}")

            settings = await self.config_manager.get_guild_settings(guild.id)
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
            logger.error(
                f"Failed to get {channel_type} channel for guild {guild.id}: {e}"
            )
            raise ConfigError(f"Failed to get channel: {str(e)}")

    async def get_monitored_channels(
        self, guild: discord.Guild
    ) -> List[discord.TextChannel]:
        """Get all monitored channels for a guild

        Args:
            guild: Discord guild

        Returns:
            List[discord.TextChannel]: List of monitored channels

        Raises:
            ConfigError: If channel retrieval fails
        """
        try:
            settings = await self.config_manager.get_guild_settings(guild.id)
            monitored_channel_ids = settings["monitored_channels"]

            # If no channels are set to be monitored, return all text channels
            if not monitored_channel_ids:
                return [
                    channel
                    for channel in guild.channels
                    if isinstance(channel, discord.TextChannel)
                ]

            # Otherwise, return only the specified channels
            channels: List[discord.TextChannel] = []
            invalid_channels: List[int] = []

            for channel_id in monitored_channel_ids:
                channel = guild.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    channels.append(channel)
                else:
                    invalid_channels.append(channel_id)
                    logger.warning(
                        f"Invalid monitored channel {channel_id} in guild {guild.id}"
                    )

            # Clean up invalid channels if found
            if invalid_channels:
                await self._remove_invalid_channels(guild.id, invalid_channels)

            return channels

        except Exception as e:
            logger.error(f"Failed to get monitored channels for guild {guild.id}: {e}")
            raise ConfigError(f"Failed to get monitored channels: {str(e)}")

    async def verify_channel_permissions(
        self, channel: discord.TextChannel, required_permissions: List[str]
    ) -> Tuple[bool, List[str]]:
        """Verify bot has required permissions in a channel

        Args:
            channel: Channel to check
            required_permissions: List of required permission names

        Returns:
            Tuple[bool, List[str]]: (Has all permissions, List of missing permissions)
        """
        try:
            bot_member = channel.guild.me
            channel_perms = channel.permissions_for(bot_member)

            missing_perms = [
                perm
                for perm in required_permissions
                if not getattr(channel_perms, perm, False)
            ]

            return not bool(missing_perms), missing_perms

        except Exception as e:
            logger.error(f"Error checking channel permissions: {e}")
            return False, ["Failed to check permissions"]

    async def add_monitored_channel(self, guild_id: int, channel_id: int) -> None:
        """Add a channel to monitored channels

        Args:
            guild_id: Guild ID
            channel_id: Channel ID to add

        Raises:
            ConfigError: If channel cannot be added
        """
        try:
            await self.config_manager.add_to_list(
                guild_id, "monitored_channels", channel_id
            )
        except Exception as e:
            logger.error(f"Failed to add monitored channel {channel_id}: {e}")
            raise ConfigError(f"Failed to add monitored channel: {str(e)}")

    async def remove_monitored_channel(self, guild_id: int, channel_id: int) -> None:
        """Remove a channel from monitored channels

        Args:
            guild_id: Guild ID
            channel_id: Channel ID to remove

        Raises:
            ConfigError: If channel cannot be removed
        """
        try:
            await self.config_manager.remove_from_list(
                guild_id, "monitored_channels", channel_id
            )
        except Exception as e:
            logger.error(f"Failed to remove monitored channel {channel_id}: {e}")
            raise ConfigError(f"Failed to remove monitored channel: {str(e)}")

    async def _remove_invalid_channels(
        self, guild_id: int, channel_ids: List[int]
    ) -> None:
        """Remove invalid channels from monitored channels

        Args:
            guild_id: Guild ID
            channel_ids: List of invalid channel IDs to remove
        """
        try:
            for channel_id in channel_ids:
                await self.remove_monitored_channel(guild_id, channel_id)
        except Exception as e:
            logger.error(f"Error removing invalid channels: {e}")

    async def get_channel_info(
        self, guild: discord.Guild
    ) -> Dict[str, Optional[discord.TextChannel]]:
        """Get all configured channels for a guild

        Args:
            guild: Discord guild

        Returns:
            Dict[str, Optional[discord.TextChannel]]: Dictionary of channel types to channels
        """
        try:
            return {
                "archive": await self.get_channel(guild, "archive"),
                "notification": await self.get_channel(guild, "notification"),
                "log": await self.get_channel(guild, "log"),
            }
        except Exception as e:
            logger.error(f"Error getting channel info: {e}")
            return {"archive": None, "notification": None, "log": None}
