"""Cleanup functionality for VideoArchiver"""

import logging
import asyncio
from typing import TYPE_CHECKING

from ..utils.file_ops import cleanup_downloads

if TYPE_CHECKING:
    from .base import VideoArchiver

logger = logging.getLogger("VideoArchiver")

CLEANUP_TIMEOUT = 15  # seconds

async def cleanup_resources(cog: "VideoArchiver") -> None:
    """Clean up all resources with proper handling"""
    try:
        # Cancel initialization if still running
        if cog._init_task and not cog._init_task.done():
            cog._init_task.cancel()
            try:
                await asyncio.wait_for(cog._init_task, timeout=CLEANUP_TIMEOUT)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        # Stop update checker
        if hasattr(cog, "update_checker"):
            try:
                await asyncio.wait_for(
                    cog.update_checker.stop(), timeout=CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                pass

        # Clean up processor
        if hasattr(cog, "processor"):
            try:
                await asyncio.wait_for(
                    cog.processor.cleanup(), timeout=CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                await cog.processor.force_cleanup()

        # Clean up queue manager
        if hasattr(cog, "queue_manager"):
            try:
                await asyncio.wait_for(
                    cog.queue_manager.cleanup(), timeout=CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                cog.queue_manager.force_stop()

        # Clean up components for each guild
        if hasattr(cog, "components"):
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

        # Clean up download directory
        if hasattr(cog, "download_path") and cog.download_path.exists():
            try:
                await cleanup_downloads(str(cog.download_path))
                cog.download_path.rmdir()
            except Exception as e:
                logger.error(f"Error cleaning up download directory: {str(e)}")

    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
        raise
    finally:
        cog.ready.clear()

async def force_cleanup_resources(cog: "VideoArchiver") -> None:
    """Force cleanup of resources when timeout occurs"""
    try:
        # Cancel all tasks
        if hasattr(cog, "processor"):
            await cog.processor.force_cleanup()

        # Force stop queue manager
        if hasattr(cog, "queue_manager"):
            cog.queue_manager.force_stop()

        # Kill any remaining FFmpeg processes
        if hasattr(cog, "ffmpeg_mgr"):
            cog.ffmpeg_mgr.kill_all_processes()

        # Clean up download directory
        if hasattr(cog, "download_path") and cog.download_path.exists():
            try:
                await cleanup_downloads(str(cog.download_path))
                cog.download_path.rmdir()
            except Exception as e:
                logger.error(f"Error force cleaning download directory: {str(e)}")

    except Exception as e:
        logger.error(f"Error during force cleanup: {str(e)}")
    finally:
        cog.ready.clear()
