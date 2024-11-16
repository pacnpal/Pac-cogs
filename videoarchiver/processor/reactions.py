"""Reaction handling for VideoProcessor"""

import logging
import asyncio
import discord

from .constants import REACTIONS

logger = logging.getLogger("VideoArchiver")

async def handle_archived_reaction(message: discord.Message, user: discord.User, db) -> None:
    """Handle reaction to archived video message"""
    try:
        # Check if the reaction is from a user (not the bot) and is the archived reaction
        if user.bot or str(message.reactions[0].emoji) != REACTIONS['archived']:
            return

        # Extract URLs from the message
        urls = []
        if message.content:
            for word in message.content.split():
                if any(s in word.lower() for s in ['http://', 'https://']):
                    urls.append(word)

        # Check each URL in the database
        for url in urls:
            result = db.get_archived_video(url)
            if result:
                discord_url = result[0]
                await message.reply(f"This video was already archived. You can find it here: {discord_url}")
                return

    except Exception as e:
        logger.error(f"Error handling archived reaction: {e}")

async def update_queue_position_reaction(message: discord.Message, position: int, bot_user) -> None:
    """Update queue position reaction"""
    try:
        for reaction in REACTIONS["numbers"]:
            try:
                await message.remove_reaction(reaction, bot_user)
            except:
                pass

        if 0 <= position < len(REACTIONS["numbers"]):
            await message.add_reaction(REACTIONS["numbers"][position])
            logger.info(
                f"Updated queue position reaction to {position + 1} for message {message.id}"
            )
    except Exception as e:
        logger.error(f"Failed to update queue position reaction: {e}")

async def update_progress_reaction(message: discord.Message, progress: float, bot_user) -> None:
    """Update progress reaction based on FFmpeg progress"""
    if not message:
        return

    try:
        # Remove old reactions in the event loop
        for reaction in REACTIONS["progress"]:
            try:
                await message.remove_reaction(reaction, bot_user)
            except Exception as e:
                logger.error(f"Failed to remove progress reaction: {e}")
                continue

        # Add new reaction based on progress
        try:
            if progress < 33:
                await message.add_reaction(REACTIONS["progress"][0])
            elif progress < 66:
                await message.add_reaction(REACTIONS["progress"][1])
            else:
                await message.add_reaction(REACTIONS["progress"][2])
        except Exception as e:
            logger.error(f"Failed to add progress reaction: {e}")

    except Exception as e:
        logger.error(f"Failed to update progress reaction: {e}")

async def update_download_progress_reaction(message: discord.Message, progress: float, bot_user) -> None:
    """Update download progress reaction"""
    if not message:
        return

    try:
        # Remove old reactions in the event loop
        for reaction in REACTIONS["download"]:
            try:
                await message.remove_reaction(reaction, bot_user)
            except Exception as e:
                logger.error(f"Failed to remove download reaction: {e}")
                continue

        # Add new reaction based on progress
        try:
            if progress <= 20:
                await message.add_reaction(REACTIONS["download"][0])
            elif progress <= 40:
                await message.add_reaction(REACTIONS["download"][1])
            elif progress <= 60:
                await message.add_reaction(REACTIONS["download"][2])
            elif progress <= 80:
                await message.add_reaction(REACTIONS["download"][3])
            elif progress < 100:
                await message.add_reaction(REACTIONS["download"][4])
            else:
                await message.add_reaction(REACTIONS["download"][5])
        except Exception as e:
            logger.error(f"Failed to add download reaction: {e}")

    except Exception as e:
        logger.error(f"Failed to update download progress reaction: {e}")
