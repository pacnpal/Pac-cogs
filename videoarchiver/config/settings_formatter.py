"""Module for formatting configuration settings"""

import logging
from typing import Dict, Any, List
from datetime import datetime
import discord  # type: ignore

# try:
# Try relative imports first
from exceptions import ConfigurationError as ConfigError

# except ImportError:
# Fall back to absolute imports if relative imports fail
# from videoarchiver.config.exceptions import ConfigurationError as ConfigError

logger = logging.getLogger("SettingsFormatter")


class SettingsFormatter:
    """Formats configuration settings for display"""

    def __init__(self):
        self.embed_color = discord.Color.blue()

    async def format_settings_embed(
        self, guild: discord.Guild, settings: Dict[str, Any]
    ) -> discord.Embed:
        """Format guild settings into a Discord embed

        Args:
            guild: Discord guild
            settings: Guild settings dictionary

        Returns:
            discord.Embed: Formatted settings embed

        Raises:
            ConfigError: If formatting fails
        """
        try:
            embed = discord.Embed(
                title="Video Archiver Settings",
                color=self.embed_color,
                timestamp=datetime.utcnow(),
            )

            # Add sections
            await self._add_core_settings(embed, guild, settings)
            await self._add_channel_settings(embed, guild, settings)
            await self._add_permission_settings(embed, guild, settings)
            await self._add_video_settings(embed, settings)
            await self._add_operation_settings(embed, settings)
            await self._add_site_settings(embed, settings)

            embed.set_footer(text="Last updated")
            return embed

        except Exception as e:
            logger.error(f"Failed to format settings embed: {e}")
            raise ConfigError(f"Failed to format settings: {str(e)}")

    async def _add_core_settings(
        self, embed: discord.Embed, guild: discord.Guild, settings: Dict[str, Any]
    ) -> None:
        """Add core settings to embed"""
        embed.add_field(
            name="Core Settings",
            value="\n".join(
                [
                    f"**Enabled:** {settings['enabled']}",
                    f"**Database Enabled:** {settings['use_database']}",
                    f"**Update Check Disabled:** {settings['disable_update_check']}",
                ]
            ),
            inline=False,
        )

    async def _add_channel_settings(
        self, embed: discord.Embed, guild: discord.Guild, settings: Dict[str, Any]
    ) -> None:
        """Add channel settings to embed"""
        # Get channels with error handling
        channels = await self._get_channel_mentions(guild, settings)

        embed.add_field(
            name="Channel Settings",
            value="\n".join(
                [
                    f"**Archive Channel:** {channels['archive']}",
                    f"**Notification Channel:** {channels['notification']}",
                    f"**Log Channel:** {channels['log']}",
                    f"**Monitored Channels:**\n{channels['monitored']}",
                ]
            ),
            inline=False,
        )

    async def _add_permission_settings(
        self, embed: discord.Embed, guild: discord.Guild, settings: Dict[str, Any]
    ) -> None:
        """Add permission settings to embed"""
        allowed_roles = await self._get_role_names(guild, settings["allowed_roles"])

        embed.add_field(
            name="Permission Settings",
            value=f"**Allowed Roles:**\n{allowed_roles}",
            inline=False,
        )

    async def _add_video_settings(
        self, embed: discord.Embed, settings: Dict[str, Any]
    ) -> None:
        """Add video settings to embed"""
        embed.add_field(
            name="Video Settings",
            value="\n".join(
                [
                    f"**Format:** {settings['video_format']}",
                    f"**Max Quality:** {settings['video_quality']}p",
                    f"**Max File Size:** {settings['max_file_size']}MB",
                ]
            ),
            inline=False,
        )

    async def _add_operation_settings(
        self, embed: discord.Embed, settings: Dict[str, Any]
    ) -> None:
        """Add operation settings to embed"""
        embed.add_field(
            name="Operation Settings",
            value="\n".join(
                [
                    f"**Delete After Repost:** {settings['delete_after_repost']}",
                    f"**Message Duration:** {settings['message_duration']} hours",
                    f"**Concurrent Downloads:** {settings['concurrent_downloads']}",
                    f"**Max Retries:** {settings['max_retries']}",
                    f"**Retry Delay:** {settings['retry_delay']}s",
                ]
            ),
            inline=False,
        )

    async def _add_site_settings(
        self, embed: discord.Embed, settings: Dict[str, Any]
    ) -> None:
        """Add site settings to embed"""
        enabled_sites = settings["enabled_sites"]
        sites_text = ", ".join(enabled_sites) if enabled_sites else "All sites"

        embed.add_field(name="Enabled Sites", value=sites_text, inline=False)

    async def _get_channel_mentions(
        self, guild: discord.Guild, settings: Dict[str, Any]
    ) -> Dict[str, str]:
        """Get channel mentions with error handling"""
        try:
            # Get channel objects
            archive_channel = guild.get_channel(settings["archive_channel"])
            notification_channel = guild.get_channel(settings["notification_channel"])
            log_channel = guild.get_channel(settings["log_channel"])

            # Get monitored channels
            monitored_channels = []
            for channel_id in settings["monitored_channels"]:
                channel = guild.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    monitored_channels.append(channel.mention)

            return {
                "archive": archive_channel.mention if archive_channel else "Not set",
                "notification": (
                    notification_channel.mention
                    if notification_channel
                    else "Same as archive"
                ),
                "log": log_channel.mention if log_channel else "Not set",
                "monitored": (
                    "\n".join(monitored_channels)
                    if monitored_channels
                    else "All channels"
                ),
            }

        except Exception as e:
            logger.error(f"Error getting channel mentions: {e}")
            return {
                "archive": "Error",
                "notification": "Error",
                "log": "Error",
                "monitored": "Error getting channels",
            }

    async def _get_role_names(self, guild: discord.Guild, role_ids: List[int]) -> str:
        """Get role names with error handling"""
        try:
            role_names = []
            for role_id in role_ids:
                role = guild.get_role(role_id)
                if role:
                    role_names.append(role.name)

            return (
                ", ".join(role_names) if role_names else "All roles (no restrictions)"
            )

        except Exception as e:
            logger.error(f"Error getting role names: {e}")
            return "Error getting roles"
