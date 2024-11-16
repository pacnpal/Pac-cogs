"""Cleanup functionality for VideoArchiver"""

import logging
import asyncio
import signal
import os
from typing import TYPE_CHECKING
from pathlib import Path

from ..utils.file_ops import cleanup_downloads

if TYPE_CHECKING:
    from .base import VideoArchiver

logger = logging.getLogger("VideoArchiver")

CLEANUP_TIMEOUT = 5  # Reduced timeout to 5 seconds
FORCE_CLEANUP_TIMEOUT = 3  # Even shorter timeout for force cleanup

async def cleanup_resources(cog: "VideoArchiver") -> None:
    """Clean up all resources with proper handling"""
    try:
        logger.info("Starting resource cleanup...")

        # Cancel initialization if still running
        if cog._init_task and not cog._init_task.done():
            logger.info("Cancelling initialization task")
            cog._init_task.cancel()
            try:
                await asyncio.wait_for(cog._init_task, timeout=CLEANUP_TIMEOUT)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("Initialization task cancellation timed out")

        # Stop update checker
        if hasattr(cog, "update_checker") and cog.update_checker:
            logger.info("Stopping update checker")
            try:
                await asyncio.wait_for(
                    cog.update_checker.stop(), timeout=CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning("Update checker stop timed out")
            cog.update_checker = None

        # Clean up processor
        if hasattr(cog, "processor") and cog.processor:
            logger.info("Cleaning up processor")
            try:
                await asyncio.wait_for(
                    cog.processor.cleanup(), timeout=CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning("Processor cleanup timed out, forcing cleanup")
                await cog.processor.force_cleanup()
            cog.processor = None

        # Clean up queue manager
        if hasattr(cog, "queue_manager") and cog.queue_manager:
            logger.info("Cleaning up queue manager")
            try:
                await asyncio.wait_for(
                    cog.queue_manager.cleanup(), timeout=CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning("Queue manager cleanup timed out, forcing stop")
                cog.queue_manager.force_stop()
            cog.queue_manager = None

        # Clean up components for each guild
        if hasattr(cog, "components"):
            logger.info("Cleaning up guild components")
            for guild_id, components in cog.components.items():
                try:
                    if "message_manager" in components:
                        await components["message_manager"].cancel_all_deletions()
                    if "downloader" in components:
                        components["downloader"] = None
                    if "ffmpeg_mgr" in components:
                        components["ffmpeg_mgr"] = None
                except Exception as e:
                    logger.error(f"Error cleaning up guild {guild_id}: {str(e)}")

            cog.components.clear()

        # Kill any FFmpeg processes
        if hasattr(cog, "ffmpeg_mgr") and cog.ffmpeg_mgr:
            logger.info("Killing FFmpeg processes")
            cog.ffmpeg_mgr.kill_all_processes()
            cog.ffmpeg_mgr = None

        # Clean up download directory
        if hasattr(cog, "download_path") and cog.download_path.exists():
            logger.info("Cleaning up download directory")
            try:
                await asyncio.wait_for(
                    cleanup_downloads(str(cog.download_path)),
                    timeout=CLEANUP_TIMEOUT
                )
                if cog.download_path.exists():
                    cog.download_path.rmdir()
            except Exception as e:
                logger.error(f"Error cleaning up download directory: {str(e)}")

        # Kill any remaining FFmpeg processes system-wide
        try:
            if os.name != 'nt':  # Unix-like systems
                os.system("pkill -9 ffmpeg")
            else:  # Windows
                os.system("taskkill /F /IM ffmpeg.exe")
        except Exception as e:
            logger.error(f"Error killing FFmpeg processes: {str(e)}")

    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
        raise
    finally:
        logger.info("Clearing ready flag")
        cog.ready.clear()

async def force_cleanup_resources(cog: "VideoArchiver") -> None:
    """Force cleanup of resources when timeout occurs"""
    try:
        logger.info("Starting force cleanup...")

        # Cancel all tasks immediately
        if hasattr(cog, "processor") and cog.processor:
            logger.info("Force cleaning processor")
            await cog.processor.force_cleanup()
            cog.processor = None

        # Force stop queue manager
        if hasattr(cog, "queue_manager") and cog.queue_manager:
            logger.info("Force stopping queue manager")
            cog.queue_manager.force_stop()
            cog.queue_manager = None

        # Kill FFmpeg processes
        if hasattr(cog, "ffmpeg_mgr") and cog.ffmpeg_mgr:
            logger.info("Force killing FFmpeg processes")
            cog.ffmpeg_mgr.kill_all_processes()
            cog.ffmpeg_mgr = None

        # Force kill any remaining FFmpeg processes system-wide
        try:
            if os.name != 'nt':  # Unix-like systems
                os.system("pkill -9 ffmpeg")
            else:  # Windows
                os.system("taskkill /F /IM ffmpeg.exe")
        except Exception as e:
            logger.error(f"Error force killing FFmpeg processes: {str(e)}")

        # Clean up download directory
        if hasattr(cog, "download_path") and cog.download_path.exists():
            logger.info("Force cleaning download directory")
            try:
                await asyncio.wait_for(
                    cleanup_downloads(str(cog.download_path)),
                    timeout=FORCE_CLEANUP_TIMEOUT
                )
                if cog.download_path.exists():
                    cog.download_path.rmdir()
            except Exception as e:
                logger.error(f"Error force cleaning download directory: {str(e)}")

        # Clear all components
        if hasattr(cog, "components"):
            logger.info("Force clearing components")
            cog.components.clear()

    except Exception as e:
        logger.error(f"Error during force cleanup: {str(e)}")
    finally:
        logger.info("Clearing ready flag")
        cog.ready.clear()
        
        # Clear all references
        cog.bot = None
        cog.processor = None
        cog.queue_manager = None
        cog.update_checker = None
        cog.ffmpeg_mgr = None
        cog.components = {}
        cog.db = None
        cog._init_task = None
        cog._cleanup_task = None
        if hasattr(cog, '_queue_task'):
            cog._queue_task = None
