"""Discord commands for VideoArchiver"""
import discord
from redbot.core import commands, app_commands, checks
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

    # Core Video Archiver Commands
    @commands.hybrid_command(name="va_settings")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def va_settings(self, ctx: commands.Context):
        """Show current video archiver settings"""
        # Defer the response immediately
        if ctx.interaction:
            await ctx.interaction.response.defer()
        
        embed = await self.config.format_settings_embed(ctx.guild)
        
        if ctx.interaction:
            await ctx.interaction.followup.send(embed=embed)
        else:
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="va_update")
    @app_commands.guild_only()
    @checks.is_owner()
    async def va_update(self, ctx: commands.Context):
        """Update yt-dlp to the latest version"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        success, message = await self.update_checker.update_yt_dlp()
        response = "✅ " + message if success else "❌ " + message
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="va_toggleupdates")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def va_toggleupdates(self, ctx: commands.Context):
        """Toggle yt-dlp update notifications"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        state = await self.config.toggle_setting(ctx.guild.id, "disable_update_check")
        status = "disabled" if state else "enabled"
        response = f"Update notifications {status}"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    # Role Management Commands
    @commands.hybrid_command(name="var_add")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to allow (leave empty for @everyone)")
    async def var_add(self, ctx: commands.Context, role: Optional[discord.Role] = None):
        """Add a role that's allowed to trigger archiving"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        if not role:
            # If no role is specified, clear the list to allow everyone
            await self.config.update_setting(ctx.guild.id, "allowed_roles", [])
            response = "Allowed role set to @everyone (all users can trigger archiving)"
        else:
            await self.config.add_to_list(ctx.guild.id, "allowed_roles", role.id)
            response = f"Added {role.name} to allowed roles"
            
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="var_remove")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to remove")
    async def var_remove(self, ctx: commands.Context, role: discord.Role):
        """Remove a role from allowed roles"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.remove_from_list(ctx.guild.id, "allowed_roles", role.id)
        response = f"Removed {role.name} from allowed roles"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="var_list")
    @app_commands.guild_only()
    async def var_list(self, ctx: commands.Context):
        """List all roles allowed to trigger archiving"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        roles = await self.config.get_setting(ctx.guild.id, "allowed_roles")
        if not roles:
            response = "No roles are currently set (all users can trigger archiving)"
        else:
            role_names = [
                r.name if r else "@everyone"
                for r in [ctx.guild.get_role(role_id) for role_id in roles]
            ]
            response = f"Allowed roles: {', '.join(role_names)}"
            
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="va_concurrent")
    @app_commands.guild_only()
    @app_commands.describe(count="Number of concurrent downloads (1-5)")
    async def va_concurrent(self, ctx: commands.Context, count: app_commands.Range[int, 1, 5]):
        """Set the number of concurrent downloads"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.update_setting(ctx.guild.id, "concurrent_downloads", count)
        response = f"Concurrent downloads set to {count}"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    # Channel Configuration Commands
    @commands.hybrid_command(name="vac_archive")
    @app_commands.guild_only()
    @app_commands.describe(channel="The archive channel")
    async def vac_archive(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the archive channel"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.update_setting(ctx.guild.id, "archive_channel", channel.id)
        response = f"Archive channel set to {channel.mention}"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="vac_notify")
    @app_commands.guild_only()
    @app_commands.describe(channel="The notification channel")
    async def vac_notify(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the notification channel (where archive messages appear)"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.update_setting(ctx.guild.id, "notification_channel", channel.id)
        response = f"Notification channel set to {channel.mention}"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="vac_log")
    @app_commands.guild_only()
    @app_commands.describe(channel="The log channel")
    async def vac_log(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the log channel for error messages and notifications"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.update_setting(ctx.guild.id, "log_channel", channel.id)
        response = f"Log channel set to {channel.mention}"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="vac_monitor")
    @app_commands.guild_only()
    @app_commands.describe(channel="The channel to monitor (leave empty to monitor all channels)")
    async def vac_monitor(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Add a channel to monitor for videos"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        if not channel:
            # If no channel is specified, clear the list to monitor all channels
            await self.config.update_setting(ctx.guild.id, "monitored_channels", [])
            response = "Now monitoring all channels for videos"
        else:
            await self.config.add_to_list(ctx.guild.id, "monitored_channels", channel.id)
            response = f"Now monitoring {channel.mention} for videos"
            
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="vac_unmonitor")
    @app_commands.guild_only()
    @app_commands.describe(channel="The channel to stop monitoring")
    async def vac_unmonitor(self, ctx: commands.Context, channel: discord.TextChannel):
        """Remove a channel from monitoring"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.remove_from_list(ctx.guild.id, "monitored_channels", channel.id)
        response = f"Stopped monitoring {channel.mention}"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    # Video Format Commands
    @commands.hybrid_command(name="va_format")
    @app_commands.guild_only()
    @app_commands.describe(format="The video format (e.g., mp4, webm)")
    async def va_format(self, ctx: commands.Context, format: Literal["mp4", "webm"]):
        """Set the video format"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.update_setting(ctx.guild.id, "video_format", format.lower())
        response = f"Video format set to {format.lower()}"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="va_quality")
    @app_commands.guild_only()
    @app_commands.describe(quality="Maximum video quality in pixels (e.g., 1080)")
    async def va_quality(self, ctx: commands.Context, quality: app_commands.Range[int, 144, 4320]):
        """Set the maximum video quality"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.update_setting(ctx.guild.id, "video_quality", quality)
        response = f"Maximum video quality set to {quality}p"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="va_maxsize")
    @app_commands.guild_only()
    @app_commands.describe(size="Maximum file size in MB")
    async def va_maxsize(self, ctx: commands.Context, size: app_commands.Range[int, 1, 100]):
        """Set the maximum file size"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.update_setting(ctx.guild.id, "max_file_size", size)
        response = f"Maximum file size set to {size}MB"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="va_toggledelete")
    @app_commands.guild_only()
    async def va_toggledelete(self, ctx: commands.Context):
        """Toggle whether to delete local files after reposting"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        state = await self.config.toggle_setting(ctx.guild.id, "delete_after_repost")
        response = f"Delete after repost: {state}"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="va_duration")
    @app_commands.guild_only()
    @app_commands.describe(hours="Duration in hours (0 for permanent)")
    async def va_duration(self, ctx: commands.Context, hours: app_commands.Range[int, 0, 720]):
        """Set how long to keep archive messages"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.update_setting(ctx.guild.id, "message_duration", hours)
        response = f"Archive message duration set to {hours} hours"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="va_template")
    @app_commands.guild_only()
    @app_commands.describe(template="Message template using {author}, {url}, and {original_message}")
    async def va_template(self, ctx: commands.Context, template: str):
        """Set the archive message template"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        await self.config.update_setting(ctx.guild.id, "message_template", template)
        response = f"Archive message template set to:\n{template}"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    # Site Management Commands
    @commands.hybrid_command(name="vas_enable")
    @app_commands.guild_only()
    @app_commands.describe(sites="Sites to enable (leave empty for all sites)")
    async def vas_enable(self, ctx: commands.Context, *, sites: Optional[str] = None):
        """Enable specific sites"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        if sites is None:
            await self.config.update_setting(ctx.guild.id, "enabled_sites", [])
            response = "All sites enabled"
        else:
            site_list = [s.strip().lower() for s in sites.split()]

            # Verify sites are valid
            with yt_dlp.YoutubeDL() as ydl:
                valid_sites = set(ie.IE_NAME.lower() for ie in ydl._ies if hasattr(ie, 'IE_NAME'))
                invalid_sites = [s for s in site_list if s not in valid_sites]
                if invalid_sites:
                    response = f"Invalid sites: {', '.join(invalid_sites)}\nValid sites: {', '.join(valid_sites)}"
                else:
                    await self.config.update_setting(ctx.guild.id, "enabled_sites", site_list)
                    response = f"Enabled sites: {', '.join(site_list)}"
                    
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)

    @commands.hybrid_command(name="vas_list")
    @app_commands.guild_only()
    async def vas_list(self, ctx: commands.Context):
        """List all available sites and currently enabled sites"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        enabled_sites = await self.config.get_setting(ctx.guild.id, "enabled_sites")
        embed = discord.Embed(title="Video Sites Configuration", color=discord.Color.blue())

        with yt_dlp.YoutubeDL() as ydl:
            # Filter out any extractors that don't have IE_NAME attribute
            all_sites = sorted(ie.IE_NAME for ie in ydl._ies if hasattr(ie, 'IE_NAME') and ie.IE_NAME is not None)

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

        if ctx.interaction:
            await ctx.interaction.followup.send(embed=embed)
        else:
            await ctx.send(embed=embed)

    # Queue Management Commands
    @commands.hybrid_command(name="vaq_status")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def vaq_status(self, ctx: commands.Context):
        """Show current queue status with basic metrics"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        status = self.processor.queue_manager.get_queue_status(ctx.guild.id)

        embed = discord.Embed(
            title="Video Processing Queue Status",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
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
            inline=False,
        )

        # Basic Metrics
        metrics = status["metrics"]
        embed.add_field(
            name="Basic Metrics",
            value=(
                f"Success Rate: {metrics['success_rate']:.1%}\n"
                f"Avg Processing Time: {metrics['avg_processing_time']:.1f}s"
            ),
            inline=False,
        )

        embed.set_footer(text="Use /vaq_metrics for detailed performance metrics")
        
        if ctx.interaction:
            await ctx.interaction.followup.send(embed=embed)
        else:
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="vaq_metrics")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def vaq_metrics(self, ctx: commands.Context):
        """Show detailed queue performance metrics"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        status = self.processor.queue_manager.get_queue_status(ctx.guild.id)
        metrics = status["metrics"]

        embed = discord.Embed(
            title="Queue Performance Metrics",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow(),
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
            inline=False,
        )

        # Resource Usage
        embed.add_field(
            name="Resource Usage",
            value=(
                f"Peak Memory Usage: {metrics['peak_memory_usage']:.1f}MB\n"
                f"Last Cleanup: {metrics['last_cleanup']}"
            ),
            inline=False,
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
            inline=False,
        )

        embed.set_footer(text="Metrics are updated in real-time as videos are processed")
        
        if ctx.interaction:
            await ctx.interaction.followup.send(embed=embed)
        else:
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="vaq_clear")
    @app_commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def vaq_clear(self, ctx: commands.Context):
        """Clear the video processing queue for this guild"""
        if ctx.interaction:
            await ctx.interaction.response.defer()
            
        cleared = await self.processor.queue_manager.clear_guild_queue(ctx.guild.id)
        response = f"Cleared {cleared} items from the queue"
        
        if ctx.interaction:
            await ctx.interaction.followup.send(response)
        else:
            await ctx.send(response)
