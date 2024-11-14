import os
import re
import discord
from redbot.core import commands, Config, data_manager, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list
from discord import app_commands
import logging
from pathlib import Path
import yt_dlp
import shutil
import asyncio
import subprocess
from typing import Optional, List, Set, Dict, Tuple
import sys
import requests
import aiohttp
from datetime import datetime, timedelta
import traceback
import contextlib
from concurrent.futures import ThreadPoolExecutor
import pkg_resources
from packaging import version

try:
    import pkg_resources
    PKG_RESOURCES_AVAILABLE = True
except ImportError:
    PKG_RESOURCES_AVAILABLE = False

# Import local utils
from .utils import VideoDownloader, secure_delete_file, cleanup_downloads, MessageManager
from .ffmpeg_manager import FFmpegManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('VideoArchiver')

class ProcessingError(Exception):
    """Custom exception for video processing errors"""
    pass

class DiscordAPIError(ProcessingError):
    """Raised when Discord API operations fail"""
    pass

class UpdateError(ProcessingError):
    """Raised when update operations fail"""
    pass

class VideoArchiver(commands.Cog):
    """Archive videos from Discord channels"""

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
        "discord_retry_attempts": 3,  # New setting for Discord API retries
        "discord_retry_delay": 5,     # New setting for Discord API retry delay
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=855847, force_registration=True)
        self.config.register_guild(**self.default_guild)

        # Initialize components dict for each guild
        self.components = {}
        
        # Track active tasks
        self.active_tasks: Dict[int, Set[asyncio.Task]] = {}
        self._task_lock = asyncio.Lock()

        # Set up download path in Red's data directory
        self.data_path = Path(data_manager.cog_data_path(self))
        self.download_path = self.data_path / "downloads"
        self.download_path.mkdir(parents=True, exist_ok=True)

        # Clean up downloads on load
        cleanup_downloads(str(self.download_path))

        # Initialize FFmpeg manager
        self.ffmpeg_mgr = FFmpegManager()

        # Start update check task
        self.update_check_task = self.bot.loop.create_task(self.check_for_updates())

    async def track_task(self, guild_id: int, task: asyncio.Task):
        """Track an active task for a guild"""
        async with self._task_lock:
            if guild_id not in self.active_tasks:
                self.active_tasks[guild_id] = set()
            self.active_tasks[guild_id].add(task)
            
            # Add error handling callback
            def handle_task_error(t):
                try:
                    exc = t.exception()
                    if exc:
                        asyncio.create_task(self.log_error(
                            self.bot.get_guild(guild_id),
                            exc,
                            "Task error"
                        ))
                except asyncio.CancelledError:
                    pass
                
                # Remove task
                asyncio.create_task(self.remove_task(guild_id, t))
            
            task.add_done_callback(handle_task_error)

    async def remove_task(self, guild_id: int, task: asyncio.Task):
        """Remove a completed task"""
        async with self._task_lock:
            if guild_id in self.active_tasks:
                self.active_tasks[guild_id].discard(task)
                # Clean up if no more tasks
                if not self.active_tasks[guild_id]:
                    del self.active_tasks[guild_id]

    async def cancel_guild_tasks(self, guild_id: int):
        """Cancel all tasks for a guild"""
        async with self._task_lock:
            if guild_id in self.active_tasks:
                tasks = self.active_tasks[guild_id]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                del self.active_tasks[guild_id]

    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        try:
            # Cancel update check task
            if self.update_check_task:
                self.update_check_task.cancel()

            # Create task to handle cleanup
            cleanup_task = asyncio.create_task(self._cleanup())
            
            # Wait for cleanup to complete
            try:
                asyncio.get_event_loop().run_until_complete(cleanup_task)
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")

        except Exception as e:
            logger.error(f"Error during cog unload: {str(e)}")

    async def _cleanup(self):
        """Handle cleanup of all resources"""
        try:
            # Cancel all tasks
            async with self._task_lock:
                all_tasks = []
                for guild_tasks in self.active_tasks.values():
                    all_tasks.extend(guild_tasks)
                for task in all_tasks:
                    task.cancel()
                await asyncio.gather(*all_tasks, return_exceptions=True)
                self.active_tasks.clear()

            # Clean up components for each guild
            for guild_id, components in self.components.items():
                try:
                    if 'message_manager' in components:
                        await components['message_manager'].cancel_all_deletions()
                    if 'downloader' in components:
                        components['downloader'] = None
                except Exception as e:
                    logger.error(f"Error cleaning up guild {guild_id}: {str(e)}")

            # Clear components
            self.components.clear()

            # Clean up download directory
            if self.download_path.exists():
                cleanup_downloads(str(self.download_path))
                shutil.rmtree(self.download_path, ignore_errors=True)

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    async def log_error(self, guild: discord.Guild, error: Exception, context: str = ""):
        """Log an error with full traceback to the guild's log channel"""
        error_msg = f"Error {context}:\n{str(error)}"
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        
        # Log to console
        logger.error(f"{error_msg}\n{tb}")
        
        # Log to Discord channel
        settings = await self.config.guild(guild).all()
        if settings["log_channel"]:
            try:
                log_channel = guild.get_channel(settings["log_channel"])
                if log_channel:
                    # Split long messages if needed
                    error_parts = [error_msg]
                    if len(tb) > 1900:  # Discord message limit is 2000
                        tb_parts = [tb[i:i+1900] for i in range(0, len(tb), 1900)]
                        error_parts.extend(tb_parts)
                    else:
                        error_parts.append(tb)
                    
                    # Send error messages with retries
                    for part in error_parts:
                        for attempt in range(settings["discord_retry_attempts"]):
                            try:
                                await log_channel.send(f"```py\n{part}```")
                                break
                            except discord.HTTPException as e:
                                if attempt == settings["discord_retry_attempts"] - 1:
                                    logger.error(f"Failed to send error log to channel after {attempt + 1} attempts: {str(e)}")
                                else:
                                    await asyncio.sleep(settings["discord_retry_delay"])
            except Exception as e:
                logger.error(f"Failed to send error log to channel: {str(e)}")

    async def check_for_updates(self):
        """Check for yt-dlp updates periodically"""
        await self.bot.wait_until_ready()
        while True:
            try:
                # Only check once per day per guild
                all_guilds = await self.config.all_guilds()
                current_time = datetime.utcnow()

                for guild_id, settings in all_guilds.items():
                    if settings.get('disable_update_check', False):
                        continue

                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue

                    last_check = settings.get('last_update_check')
                    if last_check:
                        last_check = datetime.fromisoformat(last_check)
                        if current_time - last_check < timedelta(days=1):
                            continue

                    try:
                        if not PKG_RESOURCES_AVAILABLE:
                            await self.log_error(
                                guild,
                                Exception("pkg_resources not available"),
                                "checking for updates"
                            )
                            continue

                        current_version = pkg_resources.get_distribution('yt-dlp').version
                        
                        # Use a timeout for the request
                        async with aiohttp.ClientSession() as session:
                            async with session.get(
                                'https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest',
                                timeout=aiohttp.ClientTimeout(total=10)
                            ) as response:
                                if response.status == 200:
                                    data = await response.json()
                                    latest_version = data['tag_name'].lstrip('v')

                                    # Update last check time
                                    await self.config.guild_from_id(guild_id).last_update_check.set(
                                        current_time.isoformat()
                                    )

                                    # Compare versions properly
                                    if version.parse(current_version) < version.parse(latest_version):
                                        owner = self.bot.get_user(self.bot.owner_id)
                                        if owner:
                                            # Send notification with retries
                                            for attempt in range(settings["discord_retry_attempts"]):
                                                try:
                                                    await owner.send(
                                                        f"⚠️ A new version of yt-dlp is available!\n"
                                                        f"Current: {current_version}\n"
                                                        f"Latest: {latest_version}\n"
                                                        f"Use `[p]videoarchiver updateytdlp` to update."
                                                    )
                                                    break
                                                except discord.HTTPException:
                                                    if attempt == settings["discord_retry_attempts"] - 1:
                                                        await self.log_error(
                                                            guild,
                                                            Exception("Failed to send update notification to owner"),
                                                            "checking for updates"
                                                        )
                                                    else:
                                                        await asyncio.sleep(settings["discord_retry_delay"])
                                else:
                                    raise UpdateError(f"GitHub API returned status {response.status}")

                    except asyncio.TimeoutError:
                        await self.log_error(
                            guild,
                            Exception("Request timed out"),
                            "checking for updates"
                        )
                    except Exception as e:
                        await self.log_error(guild, e, "checking for updates")

            except Exception as e:
                logger.error(f"Error in update check task: {str(e)}")

            # Wait for 6 hours before checking again
            await asyncio.sleep(21600)  # 6 hours in seconds

    async def initialize_guild_components(self, guild_id: int):
        """Initialize or update components for a guild"""
        settings = await self.config.guild_from_id(guild_id).all()

        # Ensure download directory exists
        self.download_path.mkdir(parents=True, exist_ok=True)

        # Clean up old components if they exist
        if guild_id in self.components:
            old_components = self.components[guild_id]
            if 'message_manager' in old_components:
                old_components['message_manager'].cancel_all_deletions()
            if 'downloader' in old_components:
                old_components['downloader'] = None

        self.components[guild_id] = {
            'downloader': VideoDownloader(
                str(self.download_path),
                settings['video_format'],
                settings['video_quality'],
                settings['max_file_size'],
                settings['enabled_sites'] if settings['enabled_sites'] else None,
                settings['concurrent_downloads']
            ),
            'message_manager': MessageManager(
                settings['message_duration'],
                settings['message_template']
            )
        }

    def _check_user_roles(self, member: discord.Member, allowed_roles: List[int]) -> bool:
        """Check if user has permission to trigger archiving"""
        # If no roles are set, allow all users
        if not allowed_roles:
            return True

        # Check if user has any of the allowed roles
        return any(role.id in allowed_roles for role in member.roles)

    async def log_message(self, guild: discord.Guild, message: str, level: str = "info"):
        """Send a log message to the guild's log channel if set"""
        settings = await self.config.guild(guild).all()
        if settings["log_channel"]:
            try:
                log_channel = guild.get_channel(settings["log_channel"])
                if log_channel:
                    await log_channel.send(f"[{level.upper()}] {message}")
            except discord.HTTPException:
                logger.error(f"Failed to send log message to channel: {message}")
        logger.log(getattr(logging, level.upper()), message)

    @commands.hybrid_group(name="videoarchiver", aliases=["va"])
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def videoarchiver(self, ctx: commands.Context):
        """Video Archiver configuration commands"""
        if ctx.invoked_subcommand is None:
            settings = await self.config.guild(ctx.guild).all()
            embed = discord.Embed(
                title="Video Archiver Settings",
                color=discord.Color.blue()
            )

            archive_channel = ctx.guild.get_channel(settings["archive_channel"]) if settings["archive_channel"] else None
            notification_channel = ctx.guild.get_channel(settings["notification_channel"]) if settings["notification_channel"] else None
            log_channel = ctx.guild.get_channel(settings["log_channel"]) if settings["log_channel"] else None
            monitored_channels = [ctx.guild.get_channel(c) for c in settings["monitored_channels"]]
            monitored_channels = [c.mention for c in monitored_channels if c]
            allowed_roles = [ctx.guild.get_role(r) for r in settings["allowed_roles"]]
            allowed_roles = [r.name for r in allowed_roles if r]

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
                value="\n".join(monitored_channels) if monitored_channels else "None",
                inline=False
            )
            embed.add_field(
                name="Allowed Roles",
                value=", ".join(allowed_roles) if allowed_roles else "All roles (no restrictions)",
                inline=False
            )
            embed.add_field(name="Video Format", value=settings["video_format"], inline=True)
            embed.add_field(name="Max Quality", value=f"{settings['video_quality']}p", inline=True)
            embed.add_field(name="Max File Size", value=f"{settings['max_file_size']}MB", inline=True)
            embed.add_field(name="Delete After Repost", value=str(settings["delete_after_repost"]), inline=True)
            embed.add_field(name="Message Duration", value=f"{settings['message_duration']} hours", inline=True)
            embed.add_field(name="Concurrent Downloads", value=str(settings["concurrent_downloads"]), inline=True)
            embed.add_field(name="Update Check Disabled", value=str(settings["disable_update_check"]), inline=True)

            if settings.get("last_update_check"):
                last_check = datetime.fromisoformat(settings["last_update_check"])
                embed.add_field(
                    name="Last Update Check",
                    value=last_check.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    inline=True
                )

            embed.add_field(
                name="Enabled Sites",
                value=", ".join(settings["enabled_sites"]) if settings["enabled_sites"] else "All sites",
                inline=False
            )

            # Add hardware info
            gpu_info = self.ffmpeg_mgr._gpu_info
            cpu_cores = self.ffmpeg_mgr._cpu_cores

            hardware_info = f"CPU Cores: {cpu_cores}\n"
            if gpu_info['nvidia']:
                hardware_info += "NVIDIA GPU: Available (using NVENC)\n"
            if gpu_info['amd']:
                hardware_info += "AMD GPU: Available (using AMF)\n"
            if gpu_info['intel']:
                hardware_info += "Intel GPU: Available (using QSV)\n"
            if not any(gpu_info.values()):
                hardware_info += "No GPU acceleration available (using CPU)\n"

            embed.add_field(name="Hardware Info", value=hardware_info, inline=False)

            await ctx.send(embed=embed)

    @videoarchiver.command(name="updateytdlp")
    @checks.is_owner()
    async def update_ytdlp(self, ctx: commands.Context):
        """Update yt-dlp to the latest version"""
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                if PKG_RESOURCES_AVAILABLE:
                    try:
                        new_version = pkg_resources.get_distribution('yt-dlp').version
                        await ctx.send(f"✅ Successfully updated yt-dlp to version {new_version}")
                    except Exception:
                        await ctx.send("✅ Successfully updated yt-dlp")
                else:
                    await ctx.send("✅ Successfully updated yt-dlp")
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                await ctx.send(f"❌ Failed to update yt-dlp: {error_msg}")
        except Exception as e:
            await ctx.send(f"❌ Error updating yt-dlp: {str(e)}")

    @videoarchiver.command(name="toggleupdates")
    @commands.admin_or_permissions(administrator=True)
    async def toggle_update_check(self, ctx: commands.Context):
        """Toggle yt-dlp update notifications"""
        current = await self.config.guild(ctx.guild).disable_update_check()
        await self.config.guild(ctx.guild).disable_update_check.set(not current)
        state = "disabled" if not current else "enabled"
        await ctx.send(f"Update notifications {state}")
        await self.log_message(ctx.guild, f"Update notifications {state}")

    # [Previous commands remain unchanged...]
    @videoarchiver.command(name="addrole")
    async def add_allowed_role(self, ctx: commands.Context, role: discord.Role):
        """Add a role that's allowed to trigger archiving"""
        async with self.config.guild(ctx.guild).allowed_roles() as roles:
            if role.id not in roles:
                roles.append(role.id)
        await ctx.send(f"Added {role.name} to allowed roles")
        await self.log_message(ctx.guild, f"Added role {role.name} ({role.id}) to allowed roles")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="removerole")
    async def remove_allowed_role(self, ctx: commands.Context, role: discord.Role):
        """Remove a role from allowed roles"""
        async with self.config.guild(ctx.guild).allowed_roles() as roles:
            if role.id in roles:
                roles.remove(role.id)
        await ctx.send(f"Removed {role.name} from allowed roles")
        await self.log_message(ctx.guild, f"Removed role {role.name} ({role.id}) from allowed roles")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="listroles")
    async def list_allowed_roles(self, ctx: commands.Context):
        """List all roles allowed to trigger archiving"""
        roles = await self.config.guild(ctx.guild).allowed_roles()
        if not roles:
            await ctx.send("No roles are currently allowed (all users can trigger archiving)")
            return

        role_names = [r.name for r in [ctx.guild.get_role(role_id) for role_id in roles] if r]
        await ctx.send(f"Allowed roles: {', '.join(role_names)}")

    @videoarchiver.command(name="setconcurrent")
    async def set_concurrent_downloads(self, ctx: commands.Context, count: int):
        """Set the number of concurrent downloads (1-5)"""
        if not 1 <= count <= 5:
            await ctx.send("Concurrent downloads must be between 1 and 5")
            return

        await self.config.guild(ctx.guild).concurrent_downloads.set(count)
        await ctx.send(f"Concurrent downloads set to {count}")
        await self.log_message(ctx.guild, f"Concurrent downloads set to {count}")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="setchannel")
    async def set_archive_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the archive channel"""
        await self.config.guild(ctx.guild).archive_channel.set(channel.id)
        await ctx.send(f"Archive channel set to {channel.mention}")
        await self.log_message(ctx.guild, f"Archive channel set to {channel.name} ({channel.id})")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="setnotification")
    async def set_notification_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the notification channel (where archive messages appear)"""
        await self.config.guild(ctx.guild).notification_channel.set(channel.id)
        await ctx.send(f"Notification channel set to {channel.mention}")
        await self.log_message(ctx.guild, f"Notification channel set to {channel.name} ({channel.id})")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="setlogchannel")
    async def set_log_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the log channel for error messages and notifications"""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Log channel set to {channel.mention}")
        await self.log_message(ctx.guild, f"Log channel set to {channel.name} ({channel.id})")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="addmonitor")
    async def add_monitored_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Add a channel to monitor for videos"""
        async with self.config.guild(ctx.guild).monitored_channels() as channels:
            if channel.id not in channels:
                channels.append(channel.id)
        await ctx.send(f"Now monitoring {channel.mention} for videos")
        await self.log_message(ctx.guild, f"Added {channel.name} ({channel.id}) to monitored channels")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="removemonitor")
    async def remove_monitored_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Remove a channel from monitoring"""
        async with self.config.guild(ctx.guild).monitored_channels() as channels:
            if channel.id in channels:
                channels.remove(channel.id)
        await ctx.send(f"Stopped monitoring {channel.mention}")
        await self.log_message(ctx.guild, f"Removed {channel.name} ({channel.id}) from monitored channels")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="setformat")
    async def set_video_format(self, ctx: commands.Context, format: str):
        """Set the video format (e.g., mp4, webm)"""
        await self.config.guild(ctx.guild).video_format.set(format.lower())
        await ctx.send(f"Video format set to {format.lower()}")
        await self.log_message(ctx.guild, f"Video format set to {format.lower()}")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="setquality")
    async def set_video_quality(self, ctx: commands.Context, quality: int):
        """Set the maximum video quality in pixels (e.g., 1080)"""
        await self.config.guild(ctx.guild).video_quality.set(quality)
        await ctx.send(f"Maximum video quality set to {quality}p")
        await self.log_message(ctx.guild, f"Video quality set to {quality}p")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="setmaxsize")
    async def set_max_file_size(self, ctx: commands.Context, size: int):
        """Set the maximum file size in MB"""
        await self.config.guild(ctx.guild).max_file_size.set(size)
        await ctx.send(f"Maximum file size set to {size}MB")
        await self.log_message(ctx.guild, f"Maximum file size set to {size}MB")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="toggledelete")
    async def toggle_delete_after_repost(self, ctx: commands.Context):
        """Toggle whether to delete local files after reposting"""
        current = await self.config.guild(ctx.guild).delete_after_repost()
        await self.config.guild(ctx.guild).delete_after_repost.set(not current)
        await ctx.send(f"Delete after repost: {not current}")
        await self.log_message(ctx.guild, f"Delete after repost set to: {not current}")

    @videoarchiver.command(name="setduration")
    async def set_message_duration(self, ctx: commands.Context, hours: int):
        """Set how long to keep archive messages (0 for permanent)"""
        await self.config.guild(ctx.guild).message_duration.set(hours)
        await ctx.send(f"Archive message duration set to {hours} hours")
        await self.log_message(ctx.guild, f"Message duration set to {hours} hours")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="settemplate")
    async def set_message_template(self, ctx: commands.Context, *, template: str):
        """Set the archive message template. Use {author}, {url}, and {original_message} as placeholders"""
        await self.config.guild(ctx.guild).message_template.set(template)
        await ctx.send(f"Archive message template set to:\n{template}")
        await self.log_message(ctx.guild, f"Message template updated")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="enablesites")
    async def enable_sites(self, ctx: commands.Context, *sites: str):
        """Enable specific sites (leave empty for all sites)"""
        sites = [s.lower() for s in sites]
        if not sites:
            await self.config.guild(ctx.guild).enabled_sites.set([])
            await ctx.send("All sites enabled")
        else:
            # Verify sites are valid
            with yt_dlp.YoutubeDL() as ydl:
                valid_sites = set(ie.IE_NAME.lower() for ie in ydl._ies)
                invalid_sites = [s for s in sites if s not in valid_sites]
                if invalid_sites:
                    await ctx.send(f"Invalid sites: {', '.join(invalid_sites)}\nValid sites: {', '.join(valid_sites)}")
                    return

            await self.config.guild(ctx.guild).enabled_sites.set(sites)
            await ctx.send(f"Enabled sites: {', '.join(sites)}")

        await self.log_message(ctx.guild, f"Enabled sites updated: {', '.join(sites) if sites else 'All sites'}")
        await self.initialize_guild_components(ctx.guild.id)

    @videoarchiver.command(name="listsites")
    async def list_sites(self, ctx: commands.Context):
        """List all available sites and currently enabled sites"""
        settings = await self.config.guild(ctx.guild).all()
        enabled_sites = settings["enabled_sites"]

        embed = discord.Embed(
            title="Video Sites Configuration",
            color=discord.Color.blue()
        )

        with yt_dlp.YoutubeDL() as ydl:
            all_sites = sorted(ie.IE_NAME for ie in ydl._ies if ie.IE_NAME is not None)

        # Split sites into chunks for Discord's field value limit
        chunk_size = 20
        site_chunks = [all_sites[i:i + chunk_size] for i in range(0, len(all_sites), chunk_size)]

        for i, chunk in enumerate(site_chunks, 1):
            embed.add_field(
                name=f"Available Sites ({i}/{len(site_chunks)})",
                value=", ".join(chunk),
                inline=False
            )

        embed.add_field(
            name="Currently Enabled",
            value=", ".join(enabled_sites) if enabled_sites else "All sites",
            inline=False
        )

        await ctx.send(embed=embed)

    @videoarchiver.command(name="updateffmpeg")
    @checks.is_owner()
    async def update_ffmpeg(self, ctx: commands.Context):
        """Force re-download of FFmpeg binary. Use this if FFmpeg is not working properly."""
        try:
            await ctx.send("Attempting to re-download FFmpeg...")
            if self.ffmpeg_mgr.force_download():
                await ctx.send("✅ FFmpeg successfully updated")
            else:
                await ctx.send("❌ Failed to update FFmpeg. Check logs for details.")
        except Exception as e:
            await ctx.send(f"❌ Error updating FFmpeg: {str(e)}")

    async def process_video_url(self, url: str, message: discord.Message) -> bool:
        """Process a video URL: download, reupload, and cleanup"""
        guild_id = message.guild.id

        # Initialize components if needed
        if guild_id not in self.components:
            await self.initialize_guild_components(guild_id)

        try:
            # Add initial reactions
            await message.add_reaction("📹")
            await message.add_reaction("⏳")
            await self.log_message(message.guild, f"Processing video URL: {url}")

            settings = await self.config.guild(message.guild).all()

            # Check user roles
            if not self._check_user_roles(message.author, settings["allowed_roles"]):
                await message.remove_reaction("⏳", self.bot.user)
                await message.add_reaction("🚫")
                return False

            # Download video
            success, file_path, error = await self.components[guild_id][
                "downloader"
            ].download_video(url)

            if not success:
                await message.remove_reaction("⏳", self.bot.user)
                await message.add_reaction("❌")
                await self.log_message(
                    message.guild, f"Failed to download video: {error}", "error"
                )
                return False

            # Get channels
            archive_channel = message.guild.get_channel(settings["archive_channel"])
            notification_channel = message.guild.get_channel(
                settings["notification_channel"]
                if settings["notification_channel"]
                else settings["archive_channel"]
            )

            if not archive_channel or not notification_channel:
                await self.log_message(
                    message.guild, "Required channels not found!", "error"
                )
                return False

            try:
                # Upload to archive channel
                file = discord.File(file_path)
                archive_message = await archive_channel.send(file=file)

                # Send notification with information
                notification_message = await notification_channel.send(
                    self.components[guild_id]["message_manager"].format_archive_message(
                        username=message.author.name,
                        channel=message.channel.name,
                        original_message=message.jump_url,
                    )
                )

                # Schedule notification message deletion if needed
                await self.components[guild_id][
                    "message_manager"
                ].schedule_message_deletion(
                    notification_message.id, notification_message.delete
                )

                # Update reaction to show completion
                await message.remove_reaction("⏳", self.bot.user)
                await message.add_reaction("✅")
                await self.log_message(
                    message.guild, f"Successfully archived video from {message.author}"
                )

            except discord.HTTPException as e:
                await self.log_message(
                    message.guild, f"Failed to upload video: {str(e)}", "error"
                )
                await message.remove_reaction("⏳", self.bot.user)
                await message.add_reaction("❌")
                return False

            finally:
                # Always attempt to delete the file if configured
                if settings["delete_after_repost"]:
                    if secure_delete_file(file_path):
                        await self.log_message(
                            message.guild, f"Successfully deleted file: {file_path}"
                        )
                    else:
                        await self.log_message(
                            message.guild,
                            f"Failed to delete file: {file_path}",
                            "error",
                        )
                        # Emergency cleanup
                        cleanup_downloads(str(self.download_path))

            return True

        except Exception as e:
            await self.log_message(
                message.guild, f"Error processing video: {str(e)}", "error"
            )
            await message.remove_reaction("⏳", self.bot.user)
            await message.add_reaction("❌")
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        settings = await self.config.guild(message.guild).all()

        # Check if message is in a monitored channel
        if message.channel.id not in settings["monitored_channels"]:
            return

        # Initialize components if needed
        if message.guild.id not in self.components:
            await self.initialize_guild_components(message.guild.id)

        # Find all video URLs in message
        urls = []
        with yt_dlp.YoutubeDL() as ydl:
            for ie in ydl._ies:
                if ie._VALID_URL:
                    urls.extend(re.findall(ie._VALID_URL, message.content))

        if urls:
            # Process multiple URLs concurrently but limited
            tasks = []
            semaphore = asyncio.Semaphore(settings["concurrent_downloads"])

            async def process_with_semaphore(url):
                async with semaphore:
                    return await self.process_video_url(url, message)

            for url in urls:
                tasks.append(asyncio.create_task(process_with_semaphore(url)))

            # Wait for all downloads to complete
            await asyncio.gather(*tasks)
