"""Discord commands for VideoArchiver"""
import discord
from redbot.core import commands, app_commands
from typing import Optional, Literal
import yt_dlp
from datetime import datetime

class VideoArchiverCommands(commands.Cog):
    """Command handler for VideoArchiver"""

    def __init__(self, bot, config_manager=None, update_checker=None, processor=None):
        self.bot = bot
        self.config = config_manager
        self.update_checker = update_checker
        self.processor = processor
        super().__init__()

    videoarchiver = app_commands.Group(
        name="videoarchiver",
        description="Video Archiver configuration commands",
        guild_only=True
    )

    @videoarchiver.command(name="settings")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def settings(self, interaction: discord.Interaction):
        """Show current settings"""
        embed = await self.config.format_settings_embed(interaction.guild)
        await interaction.response.send_message(embed=embed)

    @videoarchiver.command(name="updateytdlp")
    @app_commands.guild_only()
    @commands.is_owner()
    async def update_ytdlp(self, interaction: discord.Interaction):
        """Update yt-dlp to the latest version"""
        success, message = await self.update_checker.update_yt_dlp()
        await interaction.response.send_message("✅ " + message if success else "❌ " + message)

    @videoarchiver.command(name="toggleupdates")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def toggle_update_check(self, interaction: discord.Interaction):
        """Toggle yt-dlp update notifications"""
        state = await self.config.toggle_setting(interaction.guild.id, "disable_update_check")
        status = "disabled" if state else "enabled"
        await interaction.response.send_message(f"Update notifications {status}")

    @videoarchiver.command(name="addrole")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to allow (leave empty for @everyone)")
    async def add_allowed_role(self, interaction: discord.Interaction, role: Optional[discord.Role] = None):
        """Add a role that's allowed to trigger archiving"""
        if not role:
            # If no role is specified, clear the list to allow everyone
            await self.config.update_setting(interaction.guild.id, "allowed_roles", [])
            await interaction.response.send_message("Allowed role set to @everyone (all users can trigger archiving)")
            return
            
        await self.config.add_to_list(interaction.guild.id, "allowed_roles", role.id)
        await interaction.response.send_message(f"Added {role.name} to allowed roles")

    @videoarchiver.command(name="removerole")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to remove")
    async def remove_allowed_role(self, interaction: discord.Interaction, role: discord.Role):
        """Remove a role from allowed roles"""
        await self.config.remove_from_list(interaction.guild.id, "allowed_roles", role.id)
        await interaction.response.send_message(f"Removed {role.name} from allowed roles")

    @videoarchiver.command(name="listroles")
    @app_commands.guild_only()
    async def list_allowed_roles(self, interaction: discord.Interaction):
        """List all roles allowed to trigger archiving"""
        roles = await self.config.get_setting(interaction.guild.id, "allowed_roles")
        if not roles:
            await interaction.response.send_message(
                "No roles are currently set (all users can trigger archiving)"
            )
            return
        role_names = [
            r.name if r else "@everyone" 
            for r in [interaction.guild.get_role(role_id) for role_id in roles]
        ]
        await interaction.response.send_message(f"Allowed roles: {', '.join(role_names)}")

    @videoarchiver.command(name="setconcurrent")
    @app_commands.guild_only()
    @app_commands.describe(count="Number of concurrent downloads (1-5)")
    async def set_concurrent_downloads(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 5]):
        """Set the number of concurrent downloads"""
        await self.config.update_setting(interaction.guild.id, "concurrent_downloads", count)
        await interaction.response.send_message(f"Concurrent downloads set to {count}")

    @videoarchiver.command(name="setchannel")
    @app_commands.guild_only()
    @app_commands.describe(channel="The archive channel")
    async def set_archive_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the archive channel"""
        await self.config.update_setting(interaction.guild.id, "archive_channel", channel.id)
        await interaction.response.send_message(f"Archive channel set to {channel.mention}")

    @videoarchiver.command(name="setnotification")
    @app_commands.guild_only()
    @app_commands.describe(channel="The notification channel")
    async def set_notification_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the notification channel (where archive messages appear)"""
        await self.config.update_setting(
            interaction.guild.id, "notification_channel", channel.id
        )
        await interaction.response.send_message(f"Notification channel set to {channel.mention}")

    @videoarchiver.command(name="setlogchannel")
    @app_commands.guild_only()
    @app_commands.describe(channel="The log channel")
    async def set_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the log channel for error messages and notifications"""
        await self.config.update_setting(interaction.guild.id, "log_channel", channel.id)
        await interaction.response.send_message(f"Log channel set to {channel.mention}")

    @videoarchiver.command(name="addmonitor")
    @app_commands.guild_only()
    @app_commands.describe(channel="The channel to monitor (leave empty to monitor all channels)")
    async def add_monitored_channel(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        """Add a channel to monitor for videos"""
        if not channel:
            # If no channel is specified, clear the list to monitor all channels
            await self.config.update_setting(interaction.guild.id, "monitored_channels", [])
            await interaction.response.send_message("Now monitoring all channels for videos")
            return
            
        await self.config.add_to_list(interaction.guild.id, "monitored_channels", channel.id)
        await interaction.response.send_message(f"Now monitoring {channel.mention} for videos")

    @videoarchiver.command(name="removemonitor")
    @app_commands.guild_only()
    @app_commands.describe(channel="The channel to stop monitoring")
    async def remove_monitored_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Remove a channel from monitoring"""
        await self.config.remove_from_list(
            interaction.guild.id, "monitored_channels", channel.id
        )
        await interaction.response.send_message(f"Stopped monitoring {channel.mention}")

    @videoarchiver.command(name="setformat")
    @app_commands.guild_only()
    @app_commands.describe(format="The video format (e.g., mp4, webm)")
    async def set_video_format(self, interaction: discord.Interaction, format: Literal["mp4", "webm"]):
        """Set the video format"""
        await self.config.update_setting(interaction.guild.id, "video_format", format.lower())
        await interaction.response.send_message(f"Video format set to {format.lower()}")

    @videoarchiver.command(name="setquality")
    @app_commands.guild_only()
    @app_commands.describe(quality="Maximum video quality in pixels (e.g., 1080)")
    async def set_video_quality(self, interaction: discord.Interaction, quality: app_commands.Range[int, 144, 4320]):
        """Set the maximum video quality"""
        await self.config.update_setting(interaction.guild.id, "video_quality", quality)
        await interaction.response.send_message(f"Maximum video quality set to {quality}p")

    @videoarchiver.command(name="setmaxsize")
    @app_commands.guild_only()
    @app_commands.describe(size="Maximum file size in MB")
    async def set_max_file_size(self, interaction: discord.Interaction, size: app_commands.Range[int, 1, 100]):
        """Set the maximum file size"""
        await self.config.update_setting(interaction.guild.id, "max_file_size", size)
        await interaction.response.send_message(f"Maximum file size set to {size}MB")

    @videoarchiver.command(name="toggledelete")
    @app_commands.guild_only()
    async def toggle_delete_after_repost(self, interaction: discord.Interaction):
        """Toggle whether to delete local files after reposting"""
        state = await self.config.toggle_setting(interaction.guild.id, "delete_after_repost")
        await interaction.response.send_message(f"Delete after repost: {state}")

    @videoarchiver.command(name="setduration")
    @app_commands.guild_only()
    @app_commands.describe(hours="Duration in hours (0 for permanent)")
    async def set_message_duration(self, interaction: discord.Interaction, hours: app_commands.Range[int, 0, 720]):
        """Set how long to keep archive messages"""
        await self.config.update_setting(interaction.guild.id, "message_duration", hours)
        await interaction.response.send_message(f"Archive message duration set to {hours} hours")

    @videoarchiver.command(name="settemplate")
    @app_commands.guild_only()
    @app_commands.describe(template="Message template using {author}, {url}, and {original_message}")
    async def set_message_template(self, interaction: discord.Interaction, template: str):
        """Set the archive message template"""
        await self.config.update_setting(interaction.guild.id, "message_template", template)
        await interaction.response.send_message(f"Archive message template set to:\n{template}")

    @videoarchiver.command(name="enablesites")
    @app_commands.guild_only()
    @app_commands.describe(sites="Sites to enable (leave empty for all sites)")
    async def enable_sites(self, interaction: discord.Interaction, sites: Optional[str] = None):
        """Enable specific sites"""
        if sites is None:
            await self.config.update_setting(interaction.guild.id, "enabled_sites", [])
            await interaction.response.send_message("All sites enabled")
            return

        site_list = [s.strip().lower() for s in sites.split()]

        # Verify sites are valid
        with yt_dlp.YoutubeDL() as ydl:
            valid_sites = set(ie.IE_NAME.lower() for ie in ydl._ies)
            invalid_sites = [s for s in site_list if s not in valid_sites]
            if invalid_sites:
                await interaction.response.send_message(
                    f"Invalid sites: {', '.join(invalid_sites)}\nValid sites: {', '.join(valid_sites)}"
                )
                return

        await self.config.update_setting(interaction.guild.id, "enabled_sites", site_list)
        await interaction.response.send_message(f"Enabled sites: {', '.join(site_list)}")

    @videoarchiver.command(name="listsites")
    @app_commands.guild_only()
    async def list_sites(self, interaction: discord.Interaction):
        """List all available sites and currently enabled sites"""
        enabled_sites = await self.config.get_setting(interaction.guild.id, "enabled_sites")

        embed = discord.Embed(
            title="Video Sites Configuration", color=discord.Color.blue()
        )

        with yt_dlp.YoutubeDL() as ydl:
            all_sites = sorted(ie.IE_NAME for ie in ydl._ies if ie.IE_NAME is not None)

        # Split sites into chunks for Discord's field value limit
        chunk_size = 20
        site_chunks = [
            all_sites[i : i + chunk_size] for i in range(0, len(all_sites), chunk_size)
        ]

        for i, chunk in enumerate(site_chunks, 1):
            embed.add_field(
                name=f"Available Sites ({i}/{len(site_chunks)})",
                value=", ".join(chunk),
                inline=False,
            )

        embed.add_field(
            name="Currently Enabled",
            value=", ".join(enabled_sites) if enabled_sites else "All sites",
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    @videoarchiver.command(name="queue")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def show_queue(self, interaction: discord.Interaction):
        """Show current queue status with basic metrics"""
        status = self.processor.queue_manager.get_queue_status(interaction.guild.id)

        embed = discord.Embed(
            title="Video Processing Queue Status",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        # Queue Status
        embed.add_field(
            name="Queue Status",
            value=(
                f"📥 Pending: {status['pending']}\n"
                f"⚙️ Processing: {status['processing']}\n"
                f"✅ Completed: {status['completed']}\n"
                f"❌ Failed: {status['failed']}"
            ),
            inline=False
        )

        # Basic Metrics
        metrics = status['metrics']
        embed.add_field(
            name="Basic Metrics",
            value=(
                f"Success Rate: {metrics['success_rate']:.1%}\n"
                f"Avg Processing Time: {metrics['avg_processing_time']:.1f}s"
            ),
            inline=False
        )

        embed.set_footer(text="Use /videoarchiver queuemetrics for detailed performance metrics")
        await interaction.response.send_message(embed=embed)

    @videoarchiver.command(name="queuemetrics")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def show_queue_metrics(self, interaction: discord.Interaction):
        """Show detailed queue performance metrics"""
        status = self.processor.queue_manager.get_queue_status(interaction.guild.id)
        metrics = status['metrics']

        embed = discord.Embed(
            title="Queue Performance Metrics",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        # Processing Statistics
        embed.add_field(
            name="Processing Statistics",
            value=(
                f"Total Processed: {metrics['total_processed']}\n"
                f"Total Failed: {metrics['total_failed']}\n"
                f"Success Rate: {metrics['success_rate']:.1%}\n"
                f"Avg Processing Time: {metrics['avg_processing_time']:.1f}s"
            ),
            inline=False
        )

        # Resource Usage
        embed.add_field(
            name="Resource Usage",
            value=(
                f"Peak Memory Usage: {metrics['peak_memory_usage']:.1f}MB\n"
                f"Last Cleanup: {metrics['last_cleanup']}"
            ),
            inline=False
        )

        # Current Queue State
        embed.add_field(
            name="Current Queue State",
            value=(
                f"📥 Pending: {status['pending']}\n"
                f"⚙️ Processing: {status['processing']}\n"
                f"✅ Completed: {status['completed']}\n"
                f"❌ Failed: {status['failed']}"
            ),
            inline=False
        )

        embed.set_footer(text="Metrics are updated in real-time as videos are processed")
        await interaction.response.send_message(embed=embed)

    @videoarchiver.command(name="clearqueue")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def clear_queue(self, interaction: discord.Interaction):
        """Clear the video processing queue for this guild"""
        cleared = await self.processor.queue_manager.clear_guild_queue(interaction.guild.id)
        await interaction.response.send_message(f"Cleared {cleared} items from the queue")
