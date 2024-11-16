"""Event handlers for VideoArchiver"""

import logging
import discord
import asyncio
import traceback
from typing import TYPE_CHECKING

from ..processor.reactions import REACTIONS, handle_archived_reaction
from .guild import initialize_guild_components, cleanup_guild_components

if TYPE_CHECKING:
    from .base import VideoArchiver

logger = logging.getLogger("VideoArchiver")

def setup_events(cog: "VideoArchiver") -> None:
    """Set up event handlers for the cog"""

    @cog.listener()
    async def on_guild_join(guild: discord.Guild) -> None:
        """Handle bot joining a new guild"""
        if not cog.ready.is_set():
            return

        try:
            await initialize_guild_components(cog, guild.id)
            logger.info(f"Initialized components for new guild {guild.id}")
        except Exception as e:
            logger.error(f"Failed to initialize new guild {guild.id}: {str(e)}")

    @cog.listener()
    async def on_guild_remove(guild: discord.Guild) -> None:
        """Handle bot leaving a guild"""
        try:
            await cleanup_guild_components(cog, guild.id)
        except Exception as e:
            logger.error(f"Error cleaning up removed guild {guild.id}: {str(e)}")

    @cog.listener()
    async def on_message(message: discord.Message) -> None:
        """Handle new messages for video processing"""
        # Skip if not ready or if message is from DM/bot
        if not cog.ready.is_set() or message.guild is None or message.author.bot:
            return

        # Skip if message is a command
        ctx = await cog.bot.get_context(message)
        if ctx.valid:
            return

        # Process message in background task to avoid blocking
        asyncio.create_task(process_message_background(cog, message))

    @cog.listener()
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        """Handle reactions to messages"""
        if payload.user_id == cog.bot.user.id:
            return

        try:
            # Get the channel and message
            channel = cog.bot.get_channel(payload.channel_id)
            if not channel:
                return
            message = await channel.fetch_message(payload.message_id)
            if not message:
                return

            # Check if it's the archived reaction
            if str(payload.emoji) == REACTIONS["archived"]:
                # Only process if database is enabled
                if cog.db:
                    user = cog.bot.get_user(payload.user_id)
                    # Process reaction in background task
                    asyncio.create_task(handle_archived_reaction(message, user, cog.db))

        except Exception as e:
            logger.error(f"Error handling reaction: {e}")

async def process_message_background(cog: "VideoArchiver", message: discord.Message) -> None:
    """Process message in background to avoid blocking"""
    try:
        await cog.processor.process_message(message)
    except Exception as e:
        logger.error(
            f"Error processing message {message.id}: {traceback.format_exc()}"
        )
        try:
            log_channel = await cog.config_manager.get_channel(
                message.guild, "log"
            )
            if log_channel:
                await log_channel.send(
                    f"Error processing message: {str(e)}\n"
                    f"Message ID: {message.id}\n"
                    f"Channel: {message.channel.mention}"
                )
        except Exception as log_error:
            logger.error(f"Failed to log error to guild: {str(log_error)}")
