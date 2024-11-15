"""Discord commands for VideoArchiver"""
import discord
from redbot.core import commands, checks
from typing import Optional
import yt_dlp
from datetime import datetime

class VideoArchiverCommands(commands.Cog):
    """Command handler for VideoArchiver"""

    def __init__(self, bot, config_manager, update_checker, processor):
        self.bot = bot
        self.config = config_manager
        self.update_checker = update_checker
        self.processor = processor
        super().__init__()

    async def cog_load(self) -> None:
        """Initialize commands when cog loads"""
        # Ensure all commands are synced for slash command support
        await self.bot.sync_commands()

    @commands.hybrid_group(name="videoarchiver", aliases=["va"])
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def videoarchiver(self, ctx: commands.Context):
        """Video Archiver configuration commands"""
        if ctx.invoked_subcommand is None:
            embed = await self.config.format_settings_embed(ctx.guild)
            await ctx.send(embed=embed)

    @videoarchiver.command(name="updateytdlp")
    @commands.guild_only()
    @checks.is_owner()
    async def update_ytdlp(self, ctx: commands.Context):
        """Update yt-dlp to the latest version"""
        success, message = await self.update_checker.update_yt_dlp()
        await ctx.send("✅ " + message if success else "❌ " + message)

    @videoarchiver.command(name="toggleupdates")
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def toggle_update_check(self, ctx: commands.Context):
        """Toggle yt-dlp update notifications"""
        state = await self.config.toggle_setting(ctx.guild.id, "disable_update_check")
        status = "disabled" if state else "enabled"
        await ctx.send(f"Update notifications {status}")

    @videoarchiver.command(name="addrole")
    @commands.guild_only()
    async def add_allowed_role(self, ctx: commands.Context, role: discord.Role):
        """Add a role that's allowed to trigger archiving"""
        await self.config.add_to_list(ctx.guild.id, "allowed_roles", role.id)
        await ctx.send(f"Added {role.name} to allowed roles")

    @videoarchiver.command(name="removerole")
    @commands.guild_only()
    async def remove_allowed_role(self, ctx: commands.Context, role: discord.Role):
        """Remove a role from allowed roles"""
        await self.config.remove_from_list(ctx.guild.id, "allowed_roles", role.id)
        await ctx.send(f"Removed {role.name} from allowed roles")

    @videoarchiver.command(name="listroles")
    @commands.guild_only()
    async def list_allowed_roles(self, ctx: commands.Context):
        """List all roles allowed to trigger archiving"""
        roles = await self.config.get_setting(ctx.guild.id, "allowed_roles")
        if not roles:
            await ctx.send(
                "No roles are currently allowed (all users can trigger archiving)"
            )
            return
        role_names = [
            r.name for r in [ctx.guild.get_role(role_id) for role_id in roles] if r
        ]
        await ctx.send(f"Allowed roles: {', '.join(role_names)}")

    @videoarchiver.command(name="setconcurrent")
    @commands.guild_only()
    async def set_concurrent_downloads(self, ctx: commands.Context, count: int):
        """Set the number of concurrent downloads (1-5)"""
        if not 1 <= count <= 5:
            await ctx.send("Concurrent downloads must be between 1 and 5")
            return
        await self.config.update_setting(ctx.guild.id, "concurrent_downloads", count)
        await ctx.send(f"Concurrent downloads set to {count}")

    @videoarchiver.command(name="setchannel")
    @commands.guild_only()
    async def set_archive_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Set the archive channel"""
        await self.config.update_setting(ctx.guild.id, "archive_channel", channel.id)
        await ctx.send(f"Archive channel set to {channel.mention}")

    @videoarchiver.command(name="setnotification")
    @commands.guild_only()
    async def set_notification_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Set the notification channel (where archive messages appear)"""
        await self.config.update_setting(
            ctx.guild.id, "notification_channel", channel.id
        )
        await ctx.send(f"Notification channel set to {channel.mention}")

    @videoarchiver.command(name="setlogchannel")
    @commands.guild_only()
    async def set_log_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Set the log channel for error messages and notifications"""
        await self.config.update_setting(ctx.guild.id, "log_channel", channel.id)
        await ctx.send(f"Log channel set to {channel.mention}")

    @videoarchiver.command(name="addmonitor")
    @commands.guild_only()
    async def add_monitored_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Add a channel to monitor for videos"""
        await self.config.add_to_list(ctx.guild.id, "monitored_channels", channel.id)
        await ctx.send(f"Now monitoring {channel.mention} for videos")

    @videoarchiver.command(name="removemonitor")
    @commands.guild_only()
    async def remove_monitored_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """Remove a channel from monitoring"""
        await self.config.remove_from_list(
            ctx.guild.id, "monitored_channels", channel.id
        )
        await ctx.send(f"Stopped monitoring {channel.mention}")

    @videoarchiver.command(name="setformat")
    @commands.guild_only()
    async def set_video_format(self, ctx: commands.Context, format: str):
        """Set the video format (e.g., mp4, webm)"""
        await self.config.update_setting(ctx.guild.id, "video_format", format.lower())
        await ctx.send(f"Video format set to {format.lower()}")

    @videoarchiver.command(name="setquality")
    @commands.guild_only()
    async def set_video_quality(self, ctx: commands.Context, quality: int):
        """Set the maximum video quality in pixels (e.g., 1080)"""
        await self.config.update_setting(ctx.guild.id, "video_quality", quality)
        await ctx.send(f"Maximum video quality set to {quality}p")

    @videoarchiver.command(name="setmaxsize")
    @commands.guild_only()
    async def set_max_file_size(self, ctx: commands.Context, size: int):
        """Set the maximum file size in MB"""
        await self.config.update_setting(ctx.guild.id, "max_file_size", size)
        await ctx.send(f"Maximum file size set to {size}MB")

    @videoarchiver.command(name="toggledelete")
    @commands.guild_only()
    async def toggle_delete_after_repost(self, ctx: commands.Context):
        """Toggle whether to delete local files after reposting"""
        state = await self.config.toggle_setting(ctx.guild.id, "delete_after_repost")
        await ctx.send(f"Delete after repost: {state}")

    @videoarchiver.command(name="setduration")
    @commands.guild_only()
    async def set_message_duration(self, ctx: commands.Context, hours: int):
        """Set how long to keep archive messages (0 for permanent)"""
        await self.config.update_setting(ctx.guild.id, "message_duration", hours)
        await ctx.send(f"Archive message duration set to {hours} hours")

    @videoarchiver.command(name="settemplate")
    @commands.guild_only()
    async def set_message_template(self, ctx: commands.Context, *, template: str):
        """Set the archive message template. Use {author}, {url}, and {original_message} as placeholders"""
        await self.config.update_setting(ctx.guild.id, "message_template", template)
        await ctx.send(f"Archive message template set to:\n{template}")

    @videoarchiver.command(name="enablesites")
    @commands.guild_only()
    async def enable_sites(self, ctx: commands.Context, *, sites: Optional[str] = None):
        """Enable specific sites (leave empty for all sites). Separate multiple sites with spaces."""
        if sites is None:
            await self.config.update_setting(ctx.guild.id, "enabled_sites", [])
            await ctx.send("All sites enabled")
            return

        site_list = [s.strip().lower() for s in sites.split()]

        # Verify sites are valid
        with yt_dlp.YoutubeDL() as ydl:
            valid_sites = set(ie.IE_NAME.lower() for ie in ydl._ies)
            invalid_sites = [s for s in site_list if s not in valid_sites]
            if invalid_sites:
                await ctx.send(
                    f"Invalid sites: {', '.join(invalid_sites)}\nValid sites: {', '.join(valid_sites)}"
                )
                return

        await self.config.update_setting(ctx.guild.id, "enabled_sites", site_list)
        await ctx.send(f"Enabled sites: {', '.join(site_list)}")

    @videoarchiver.command(name="listsites")
    @commands.guild_only()
    async def list_sites(self, ctx: commands.Context):
        """List all available sites and currently enabled sites"""
        enabled_sites = await self.config.get_setting(ctx.guild.id, "enabled_sites")

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

        await ctx.send(embed=embed)

    @videoarchiver.command(name="queue")
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def show_queue(self, ctx: commands.Context):
        """Show current queue status with basic metrics"""
        status = self.processor.queue_manager.get_queue_status(ctx.guild.id)

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

        embed.set_footer(text="Use [p]va queuemetrics for detailed performance metrics")
        await ctx.send(embed=embed)

    @videoarchiver.command(name="queuemetrics")
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def show_queue_metrics(self, ctx: commands.Context):
        """Show detailed queue performance metrics"""
        status = self.processor.queue_manager.get_queue_status(ctx.guild.id)
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
        await ctx.send(embed=embed)

    @videoarchiver.command(name="clearqueue")
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def clear_queue(self, ctx: commands.Context):
        """Clear the video processing queue for this guild"""
        cleared = await self.processor.queue_manager.clear_guild_queue(ctx.guild.id)
        await ctx.send(f"Cleared {cleared} items from the queue")
