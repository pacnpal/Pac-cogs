"""Reaction handling for VideoProcessor"""

import logging
import asyncio
import re
from typing import List, Optional
import discord  # type: ignore
from urllib.parse import urlparse

# try:
# Try relative imports first
from ..processor.constants import (
    REACTIONS,
    ReactionType,
    get_reaction,
    get_progress_emoji,
)
from ..database.video_archive_db import VideoArchiveDB

# except ImportError:
# Fall back to absolute imports if relative imports fail
# from videoarchiver.processor.constants import (
#     REACTIONS,
#     ReactionType,
#     get_reaction,
#     get_progress_emoji,
# )
# from videoarchiver.database.video_archive_db import VideoArchiveDB

logger = logging.getLogger("VideoArchiver")


async def handle_archived_reaction(
    message: discord.Message, user: discord.User, db: VideoArchiveDB
) -> None:
    """
    Handle reaction to archived video message.

    Args:
        message: The Discord message that was reacted to
        user: The user who added the reaction
        db: Database instance for checking archived videos
    """
    try:
        # Check if the reaction is from a user (not the bot) and is the archived reaction
        if user.bot or str(message.reactions[0].emoji) != get_reaction(
            ReactionType.ARCHIVED
        ):
            return

        # Extract URLs from the message using regex
        url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')
        urls = url_pattern.findall(message.content) if message.content else []

        # Check each URL in the database
        for url in urls:
            # Ensure URL has proper scheme
            if url.startswith("www."):
                url = "http://" + url

            # Validate URL
            try:
                result = urlparse(url)
                if not all([result.scheme, result.netloc]):
                    continue
            except Exception:
                continue

            result = db.get_archived_video(url)
            if result:
                discord_url = result[0]
                await message.reply(
                    f"This video was already archived. You can find it here: {discord_url}"
                )
                return

    except Exception as e:
        logger.error(f"Error handling archived reaction: {e}", exc_info=True)


async def update_queue_position_reaction(
    message: discord.Message, position: int, bot_user: discord.ClientUser
) -> None:
    """
    Update queue position reaction.

    Args:
        message: The Discord message to update reactions on
        position: Queue position (0-based index)
        bot_user: The bot's user instance for managing reactions
    """
    try:
        numbers = get_reaction(ReactionType.NUMBERS)
        if not isinstance(numbers, list):
            logger.error("Numbers reaction is not a list")
            return

        # Remove old reactions
        for reaction in numbers:
            try:
                await message.remove_reaction(reaction, bot_user)
            except discord.HTTPException as e:
                logger.warning(f"Failed to remove number reaction: {e}")
            except Exception as e:
                logger.error(f"Unexpected error removing number reaction: {e}")

        # Add new reaction if position is valid
        if 0 <= position < len(numbers):
            try:
                await message.add_reaction(numbers[position])
                logger.info(
                    f"Updated queue position reaction to {position + 1} for message {message.id}"
                )
            except discord.HTTPException as e:
                logger.error(f"Failed to add queue position reaction: {e}")

    except Exception as e:
        logger.error(f"Failed to update queue position reaction: {e}", exc_info=True)


async def update_progress_reaction(
    message: discord.Message, progress: float, bot_user: discord.ClientUser
) -> None:
    """
    Update progress reaction based on FFmpeg progress.

    Args:
        message: The Discord message to update reactions on
        progress: Progress value between 0 and 100
        bot_user: The bot's user instance for managing reactions
    """
    if not message:
        return

    try:
        progress_emojis = get_reaction(ReactionType.PROGRESS)
        if not isinstance(progress_emojis, list):
            logger.error("Progress reaction is not a list")
            return

        # Remove old reactions
        for reaction in progress_emojis:
            try:
                await message.remove_reaction(reaction, bot_user)
            except discord.HTTPException as e:
                logger.warning(f"Failed to remove progress reaction: {e}")
            except Exception as e:
                logger.error(f"Unexpected error removing progress reaction: {e}")

        # Add new reaction based on progress
        try:
            normalized_progress = progress / 100  # Convert to 0-1 range
            emoji = get_progress_emoji(normalized_progress, progress_emojis)
            await message.add_reaction(emoji)
        except Exception as e:
            logger.error(f"Failed to add progress reaction: {e}")

    except Exception as e:
        logger.error(f"Failed to update progress reaction: {e}", exc_info=True)


async def update_download_progress_reaction(
    message: discord.Message, progress: float, bot_user: discord.ClientUser
) -> None:
    """
    Update download progress reaction.

    Args:
        message: The Discord message to update reactions on
        progress: Progress value between 0 and 100
        bot_user: The bot's user instance for managing reactions
    """
    if not message:
        return

    try:
        download_emojis = get_reaction(ReactionType.DOWNLOAD)
        if not isinstance(download_emojis, list):
            logger.error("Download reaction is not a list")
            return

        # Remove old reactions
        for reaction in download_emojis:
            try:
                await message.remove_reaction(reaction, bot_user)
            except discord.HTTPException as e:
                logger.warning(f"Failed to remove download reaction: {e}")
            except Exception as e:
                logger.error(f"Unexpected error removing download reaction: {e}")

        # Add new reaction based on progress
        try:
            normalized_progress = progress / 100  # Convert to 0-1 range
            emoji = get_progress_emoji(normalized_progress, download_emojis)
            await message.add_reaction(emoji)
        except Exception as e:
            logger.error(f"Failed to add download reaction: {e}")

    except Exception as e:
        logger.error(f"Failed to update download progress reaction: {e}", exc_info=True)
