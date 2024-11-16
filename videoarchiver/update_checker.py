"""Update checker for yt-dlp"""
import logging
from importlib.metadata import version as get_package_version
from datetime import datetime, timedelta
import aiohttp
from packaging import version
import discord
from typing import Optional, Tuple, Dict, Any
import asyncio
import sys
import json
from pathlib import Path
import subprocess
import tempfile
import os
import shutil

from .exceptions import UpdateError

logger = logging.getLogger('VideoArchiver')

class UpdateChecker:
    """Handles checking for yt-dlp updates"""

    GITHUB_API_URL = 'https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest'
    UPDATE_CHECK_INTERVAL = 21600  # 6 hours in seconds
    MAX_RETRIES = 3
    RETRY_DELAY = 5
    REQUEST_TIMEOUT = 30
    SUBPROCESS_TIMEOUT = 300  # 5 minutes
    
    def __init__(self, bot, config_manager):
        self.bot = bot
        self.config_manager = config_manager
        self._check_task = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limit_reset = 0
        self._remaining_requests = 60
        self._last_version_check: Dict[int, datetime] = {}

    async def _init_session(self) -> None:
        """Initialize aiohttp session with proper headers"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    'Accept': 'application/vnd.github.v3+json',
                    'User-Agent': 'VideoArchiver-Bot'
                }
            )

    async def start(self) -> None:
        """Start the update checker task"""
        if self._check_task is None:
            await self._init_session()
            self._check_task = self.bot.loop.create_task(self._check_loop())
            logger.info("Update checker task started")

    async def stop(self) -> None:
        """Stop the update checker task and cleanup"""
        if self._check_task:
            self._check_task.cancel()
            self._check_task = None
            
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            
        logger.info("Update checker task stopped")

    async def _check_loop(self) -> None:
        """Periodic update check loop with improved error handling"""
        await self.bot.wait_until_ready()
        
        while True:
            try:
                for guild in self.bot.guilds:
                    try:
                        settings = await self.config_manager.get_guild_settings(guild.id)
                        if settings.get('disable_update_check', False):
                            continue

                        current_time = datetime.utcnow()

                        # Check if we've checked recently
                        last_check = self._last_version_check.get(guild.id)
                        if last_check and (current_time - last_check).total_seconds() < self.UPDATE_CHECK_INTERVAL:
                            continue

                        # Check rate limits
                        if self._remaining_requests <= 0:
                            if current_time.timestamp() < self._rate_limit_reset:
                                continue
                            # Reset rate limit counters
                            self._remaining_requests = 60
                            self._rate_limit_reset = 0

                        await self._check_guild(guild, settings)
                        self._last_version_check[guild.id] = current_time

                    except Exception as e:
                        logger.error(f"Error checking updates for guild {guild.id}: {str(e)}")
                        continue

            except Exception as e:
                logger.error(f"Error in update check task: {str(e)}")

            await asyncio.sleep(self.UPDATE_CHECK_INTERVAL)

    async def _check_guild(self, guild: discord.Guild, settings: dict) -> None:
        """Check updates for a specific guild with improved error handling"""
        try:
            current_version = self._get_current_version()
            if not current_version:
                await self._log_error(
                    guild,
                    UpdateError("Could not determine current yt-dlp version"),
                    "checking current version"
                )
                return

            latest_version = await self._get_latest_version()
            if not latest_version:
                return  # Error already logged in _get_latest_version

            # Update last check time
            await self.config_manager.update_setting(
                guild.id,
                "last_update_check",
                datetime.utcnow().isoformat()
            )

            # Compare versions
            if version.parse(current_version) < version.parse(latest_version):
                await self._notify_update(guild, current_version, latest_version, settings)

        except Exception as e:
            await self._log_error(guild, e, "checking for updates")

    def _get_current_version(self) -> Optional[str]:
        """Get current yt-dlp version with error handling"""
        try:
            return get_package_version('yt-dlp')
        except Exception as e:
            logger.error(f"Error getting current version: {str(e)}")
            return None

    async def _get_latest_version(self) -> Optional[str]:
        """Get the latest version from GitHub with retries and rate limit handling"""
        await self._init_session()
        
        for attempt in range(self.MAX_RETRIES):
            try:
                async with self._session.get(
                    self.GITHUB_API_URL,
                    timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
                ) as response:
                    # Update rate limit info
                    self._remaining_requests = int(response.headers.get('X-RateLimit-Remaining', 0))
                    self._rate_limit_reset = int(response.headers.get('X-RateLimit-Reset', 0))

                    if response.status == 200:
                        data = await response.json()
                        return data['tag_name'].lstrip('v')
                    elif response.status == 403 and 'X-RateLimit-Remaining' in response.headers:
                        logger.warning("GitHub API rate limit reached")
                        return None
                    elif response.status == 404:
                        raise UpdateError("GitHub API endpoint not found")
                    else:
                        raise UpdateError(f"GitHub API returned status {response.status}")

            except asyncio.TimeoutError:
                logger.error(f"Timeout getting latest version (attempt {attempt + 1}/{self.MAX_RETRIES})")
                if attempt == self.MAX_RETRIES - 1:
                    return None
                    
            except Exception as e:
                logger.error(f"Error getting latest version (attempt {attempt + 1}/{self.MAX_RETRIES}): {str(e)}")
                if attempt == self.MAX_RETRIES - 1:
                    return None
                    
            await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))

        return None

    async def _notify_update(
        self,
        guild: discord.Guild,
        current_version: str,
        latest_version: str,
        settings: dict
    ) -> None:
        """Notify about available updates with retry mechanism"""
        owner = self.bot.get_user(self.bot.owner_id)
        if not owner:
            await self._log_error(
                guild,
                UpdateError("Could not find bot owner"),
                "sending update notification"
            )
            return

        message = (
            f"⚠️ A new version of yt-dlp is available!\n"
            f"Current: {current_version}\n"
            f"Latest: {latest_version}\n"
            f"Use `[p]videoarchiver updateytdlp` to update."
        )

        for attempt in range(settings.get("discord_retry_attempts", 3)):
            try:
                await owner.send(message)
                return
            except discord.HTTPException as e:
                if attempt == settings["discord_retry_attempts"] - 1:
                    await self._log_error(
                        guild,
                        UpdateError(f"Failed to send update notification: {str(e)}"),
                        "sending update notification"
                    )
                else:
                    await asyncio.sleep(settings.get("discord_retry_delay", 5))

    async def _log_error(self, guild: discord.Guild, error: Exception, context: str) -> None:
        """Log an error to the guild's log channel with enhanced formatting"""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        error_message = f"[{timestamp}] Error {context}: {str(error)}"
        
        log_channel = await self.config_manager.get_channel(guild, "log")
        if log_channel:
            try:
                await log_channel.send(f"```\n{error_message}\n```")
            except discord.HTTPException as e:
                logger.error(f"Failed to send error to log channel: {str(e)}")
                
        logger.error(f"Guild {guild.id} - {error_message}")

    async def update_yt_dlp(self) -> Tuple[bool, str]:
        """Update yt-dlp to the latest version with improved error handling"""
        temp_dir = None
        try:
            # Create temporary directory for pip output
            temp_dir = tempfile.mkdtemp(prefix='ytdlp_update_')
            log_file = Path(temp_dir) / 'pip_log.txt'

            # Prepare pip command
            cmd = [
                sys.executable,
                '-m',
                'pip',
                'install',
                '--upgrade',
                'yt-dlp',
                '--log',
                str(log_file)
            ]

            # Run pip in subprocess with timeout
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.SUBPROCESS_TIMEOUT
                )
            except asyncio.TimeoutError:
                process.kill()
                raise UpdateError("Update process timed out")

            if process.returncode == 0:
                new_version = self._get_current_version()
                if new_version:
                    return True, f"Successfully updated to version {new_version}"
                return True, "Successfully updated (version unknown)"
            else:
                # Read detailed error log
                error_details = "Unknown error"
                if log_file.exists():
                    try:
                        error_details = log_file.read_text(errors='ignore')
                    except Exception:
                        pass
                return False, f"Failed to update: {error_details}"

        except Exception as e:
            return False, f"Error updating: {str(e)}"

        finally:
            # Cleanup temporary directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.error(f"Failed to cleanup temporary directory: {str(e)}")
