"""Core VideoProcessor class that manages video processing operations"""

import logging
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from typing import Dict, Any, Optional

from .message_handler import MessageHandler
from .queue_handler import QueueHandler
from .progress_tracker import ProgressTracker
from .reactions import REACTIONS

logger = logging.getLogger("VideoArchiver")

class VideoProcessor:
    """Handles video processing operations"""

    def __init__(
        self,
        bot,
        config_manager,
        components,
        queue_manager=None,
        ffmpeg_mgr=None,
        db=None
    ):
        self.bot = bot
        self.config = config_manager
        self.components = components
        self.ffmpeg_mgr = ffmpeg_mgr
        self.db = db

        # Initialize handlers
        self.queue_handler = QueueHandler(bot, config_manager, components)
        self.message_handler = MessageHandler(bot, config_manager, queue_manager)
        self.progress_tracker = ProgressTracker()

        # Pass db to queue handler if it exists
        if self.db:
            self.queue_handler.db = self.db

        # Start queue processing
        logger.info("Starting video processing queue...")
        self._queue_task = None
        if queue_manager:
            self._queue_task = self.bot.loop.create_task(
                queue_manager.process_queue(self.queue_handler.process_video)
            )
            logger.info("Video processing queue started successfully")

    async def process_message(self, message: discord.Message) -> None:
        """Process a message for video content"""
        await self.message_handler.process_message(message)

    async def cleanup(self):
        """Clean up resources and stop processing"""
        try:
            logger.info("Starting VideoProcessor cleanup...")
            
            # Clean up queue handler
            try:
                await self.queue_handler.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up queue handler: {e}")

            # Clean up FFmpeg manager
            if self.ffmpeg_mgr:
                try:
                    self.ffmpeg_mgr.kill_all_processes()
                except Exception as e:
                    logger.error(f"Error cleaning up FFmpeg manager: {e}")

            # Cancel queue processing task
            if self._queue_task and not self._queue_task.done():
                self._queue_task.cancel()
                try:
                    await self._queue_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling queue task: {e}")

            logger.info("VideoProcessor cleanup completed successfully")

        except Exception as e:
            logger.error(f"Error during VideoProcessor cleanup: {str(e)}", exc_info=True)
            raise

    async def force_cleanup(self):
        """Force cleanup of resources when normal cleanup fails"""
        try:
            logger.info("Starting force cleanup of VideoProcessor...")

            # Force cleanup queue handler
            try:
                await self.queue_handler.force_cleanup()
            except Exception as e:
                logger.error(f"Error force cleaning queue handler: {e}")

            # Force cleanup FFmpeg
            if self.ffmpeg_mgr:
                try:
                    self.ffmpeg_mgr.kill_all_processes()
                except Exception as e:
                    logger.error(f"Error force cleaning FFmpeg manager: {e}")

            # Force cancel queue task
            if self._queue_task and not self._queue_task.done():
                self._queue_task.cancel()

            logger.info("VideoProcessor force cleanup completed")

        except Exception as e:
            logger.error(f"Error during VideoProcessor force cleanup: {str(e)}", exc_info=True)

    async def show_queue_details(self, ctx: commands.Context):
        """Display detailed queue status and progress information"""
        try:
            # Get queue status
            queue_status = self.queue_manager.get_queue_status(ctx.guild.id)

            # Create embed for queue overview
            embed = discord.Embed(
                title="Queue Status Details",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow(),
            )

            # Queue statistics
            embed.add_field(
                name="Queue Statistics",
                value=f"```\n"
                f"Pending: {queue_status['pending']}\n"
                f"Processing: {queue_status['processing']}\n"
                f"Completed: {queue_status['completed']}\n"
                f"Failed: {queue_status['failed']}\n"
                f"Success Rate: {queue_status['metrics']['success_rate']:.1%}\n"
                f"Avg Processing Time: {queue_status['metrics']['avg_processing_time']:.1f}s\n"
                f"```",
                inline=False,
            )

            # Active operations
            active_ops = self.progress_tracker.get_active_operations()

            # Active downloads
            downloads = active_ops['downloads']
            if downloads:
                active_downloads = ""
                for url, progress in downloads.items():
                    active_downloads += (
                        f"URL: {url[:50]}...\n"
                        f"Progress: {progress.get('percent', 0):.1f}%\n"
                        f"Speed: {progress.get('speed', 'N/A')}\n"
                        f"ETA: {progress.get('eta', 'N/A')}\n"
                        f"Size: {progress.get('downloaded_bytes', 0)}/{progress.get('total_bytes', 0)} bytes\n"
                        f"Started: {progress.get('start_time', 'N/A')}\n"
                        f"Retries: {progress.get('retries', 0)}\n"
                        f"-------------------\n"
                    )
                embed.add_field(
                    name="Active Downloads",
                    value=f"```\n{active_downloads}```",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Active Downloads",
                    value="```\nNo active downloads```",
                    inline=False,
                )

            # Active compressions
            compressions = active_ops['compressions']
            if compressions:
                active_compressions = ""
                for file_id, progress in compressions.items():
                    active_compressions += (
                        f"File: {progress.get('filename', 'Unknown')}\n"
                        f"Progress: {progress.get('percent', 0):.1f}%\n"
                        f"Time Elapsed: {progress.get('elapsed_time', 'N/A')}\n"
                        f"Input Size: {progress.get('input_size', 0)} bytes\n"
                        f"Current Size: {progress.get('current_size', 0)} bytes\n"
                        f"Target Size: {progress.get('target_size', 0)} bytes\n"
                        f"Codec: {progress.get('codec', 'Unknown')}\n"
                        f"Hardware Accel: {progress.get('hardware_accel', False)}\n"
                        f"-------------------\n"
                    )
                embed.add_field(
                    name="Active Compressions",
                    value=f"```\n{active_compressions}```",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Active Compressions",
                    value="```\nNo active compressions```",
                    inline=False,
                )

            # Error statistics
            if queue_status["metrics"]["errors_by_type"]:
                error_stats = "\n".join(
                    f"{error_type}: {count}"
                    for error_type, count in queue_status["metrics"]["errors_by_type"].items()
                )
                embed.add_field(
                    name="Error Statistics",
                    value=f"```\n{error_stats}```",
                    inline=False,
                )

            # Hardware acceleration statistics
            embed.add_field(
                name="Hardware Statistics",
                value=f"```\n"
                f"Hardware Accel Failures: {queue_status['metrics']['hardware_accel_failures']}\n"
                f"Compression Failures: {queue_status['metrics']['compression_failures']}\n"
                f"Peak Memory Usage: {queue_status['metrics']['peak_memory_usage']:.1f}MB\n"
                f"```",
                inline=False,
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error showing queue details: {str(e)}", exc_info=True)
            await ctx.send(f"Error getting queue details: {str(e)}")
