"""VideoArchiver cog for Red-DiscordBot"""
import logging
import sys
from pathlib import Path
from typing import Optional
import asyncio
import pkg_resources

from redbot.core.bot import Red
from redbot.core.utils import get_end_user_data_statement
from redbot.core.errors import CogLoadError
from .video_archiver import VideoArchiver
from .exceptions import ProcessingError

__version__ = "1.0.0"

log = logging.getLogger("red.videoarchiver")

REQUIRED_PYTHON_VERSION = (3, 8, 0)
REQUIRED_PACKAGES = {
    'yt-dlp': '2024.11.4',
    'ffmpeg-python': '0.2.0',
    'aiohttp': '3.8.0',
    'packaging': '20.0',
}

def check_dependencies() -> Optional[str]:
    """Check if all required dependencies are met."""
    # Check Python version
    if sys.version_info < REQUIRED_PYTHON_VERSION:
        return (
            f"Python {'.'.join(map(str, REQUIRED_PYTHON_VERSION))} or higher is required. "
            f"Current version: {'.'.join(map(str, sys.version_info[:3]))}"
        )

    # Check required packages
    missing_packages = []
    outdated_packages = []
    
    for package, min_version in REQUIRED_PACKAGES.items():
        try:
            installed_version = pkg_resources.get_distribution(package).version
            if pkg_resources.parse_version(installed_version) < pkg_resources.parse_version(min_version):
                outdated_packages.append(f"{package}>={min_version}")
        except pkg_resources.DistributionNotFound:
            missing_packages.append(f"{package}>={min_version}")

    if missing_packages or outdated_packages:
        error_msg = []
        if missing_packages:
            error_msg.append(f"Missing packages: {', '.join(missing_packages)}")
        if outdated_packages:
            error_msg.append(f"Outdated packages: {', '.join(outdated_packages)}")
        return "\n".join(error_msg)

    return None

async def setup(bot: Red) -> None:
    """Load VideoArchiver cog with enhanced error handling."""
    try:
        # Check dependencies
        if dependency_error := check_dependencies():
            raise CogLoadError(
                f"Dependencies not met:\n{dependency_error}\n"
                "Please install/upgrade the required packages."
            )

        # Check for ffmpeg
        try:
            import ffmpeg
            ffmpeg.probe('ffmpeg-version')
        except Exception:
            raise CogLoadError(
                "FFmpeg is not installed or not found in PATH. "
                "Please install FFmpeg before loading this cog."
            )

        # Initialize cog
        cog = VideoArchiver(bot)
        await bot.add_cog(cog)
        
        # Store cog instance for proper cleanup
        bot._videoarchiver = cog
        
        log.info(
            f"VideoArchiver v{__version__} loaded successfully\n"
            f"Python version: {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}\n"
            f"Running on: {sys.platform}"
        )

    except CogLoadError as e:
        log.error(f"Failed to load VideoArchiver: {str(e)}")
        raise
    except Exception as e:
        log.exception("Unexpected error loading VideoArchiver:", exc_info=e)
        raise CogLoadError(f"Unexpected error: {str(e)}")

async def teardown(bot: Red) -> None:
    """Clean up when cog is unloaded."""
    try:
        # Get cog instance
        cog = getattr(bot, '_videoarchiver', None)
        if cog:
            # Perform async cleanup
            await cog.cog_unload()
            # Remove stored instance
            delattr(bot, '_videoarchiver')
            
        log.info("VideoArchiver unloaded successfully")
        
    except Exception as e:
        log.exception("Error during VideoArchiver teardown:", exc_info=e)
        # Don't raise here to ensure clean unload even if cleanup fails

def get_data_statement() -> str:
    """Get the end user data statement."""
    return """This cog stores the following user data:
1. User IDs for tracking video processing permissions
2. Message IDs and channel IDs for tracking processed videos
3. Guild-specific settings and configurations

Data is stored locally and is necessary for the cog's functionality.
No data is shared with external services.

Users can request data deletion by:
1. Removing the bot from their server
2. Using the bot's data deletion commands
3. Contacting the bot owner

Note: Video files are temporarily stored during processing and are 
automatically deleted after successful upload or on error."""

# Set end user data statement
__red_end_user_data_statement__ = get_data_statement()
